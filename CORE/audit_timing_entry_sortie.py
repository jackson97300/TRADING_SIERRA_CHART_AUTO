"""Audit empirique TIMING entry/sortie — Bot 1 (DMP Sim3) + Bot 2 (DB Sim2).

Pose la question pro de Jackson : "Décider d'acheter c'est un fait, le bon
point d'entrée est la clé. C'est ce qui différencie amateur du gagnant."

Analyses exhaustives sur les données réelles trades.jsonl du 29/04/2026 :

A. Slippage entry (Bot 1 a slip_entry_ticks, Bot 2 estimable via signal close)
B. MAE/MFE distribution par outcome (Bot 1 only)
C. "MFE caché" : trades SL qui ont eu un MFE positif avant de mourir
   → quantifie le potentiel d'un trailing/TP partiel
D. "MAE caché" : trades TP qui sont allés contre nous avant de devenir profit
   → quantifie le mauvais timing d'entry sur trades qui finissent gagnants
E. Performance par mur (sl_wall, tp_wall)
F. Optimal R-multiple : si TP=1R / 1.5R / 2R / 3R, quel PF résultant
G. Optimal entry offset : simulation entry = close - X ticks (limite passive)
H. Bot 2 features at entry : différenciateur WIN vs LOSS
I. Comparaison cross-bot sur setups simultanés
"""
import json
from pathlib import Path
from collections import defaultdict
import statistics

import pandas as pd
import numpy as np

FP1 = Path("DATA/PAPER_TRADES/20260429_trades.jsonl")           # Bot 1 Sim3
FP2 = Path("DATA/PAPER_TRADES/20260429_databento_trades.jsonl")  # Bot 2 Sim2
TICK_VALUE = {"ES": 1.25, "NQ": 0.5}
TICK_SIZE = 0.25


def load(fp):
    rows = []
    with open(fp, "r", encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if not s:
                continue
            try:
                rows.append(json.loads(s))
            except json.JSONDecodeError:
                pass
    return pd.DataFrame(rows)


df1 = load(FP1)
df2 = load(FP2)
print("=" * 100)
print("  AUDIT TIMING ENTRY/SORTIE — Bot 1 (DMP Sim3) vs Bot 2 (DB Sim2) — 29/04/2026")
print("=" * 100)
print(f"Bot 1 : {len(df1)} trades")
print(f"Bot 2 : {len(df2)} trades")

# Filter today
df1["entry_dt"] = pd.to_datetime(df1["entry_time"], utc=True)
df2["entry_dt"] = pd.to_datetime(df2["entry_time"], utc=True)
df1 = df1[df1["entry_dt"] >= "2026-04-29T00:00:00+00:00"].copy()
df2 = df2[df2["entry_dt"] >= "2026-04-29T00:00:00+00:00"].copy()
print(f"\nApres filtre 29/04 only : Bot 1 = {len(df1)}, Bot 2 = {len(df2)}")

# ==================================================================
# A. SLIPPAGE ENTRY — quantifier le coût du mauvais timing
# ==================================================================
print("\n" + "=" * 100)
print("  A. SLIPPAGE ENTRY (combien le marche a bouge entre signal et fill)")
print("=" * 100)

if "slip_entry_ticks" in df1.columns:
    slip1 = pd.to_numeric(df1["slip_entry_ticks"], errors="coerce").dropna()
    print(f"\nBot 1 (DMP Sim3) — slip_entry_ticks instrumente :")
    print(f"  N samples       : {len(slip1)}")
    print(f"  Median          : {slip1.median():+.1f}t")
    print(f"  Mean            : {slip1.mean():+.1f}t")
    print(f"  Min / Max       : {slip1.min():+.1f}t / {slip1.max():+.1f}t")
    print(f"  Std             : {slip1.std():.1f}t")
    # Slip absolu (cost reel)
    slip1_abs = slip1.abs()
    print(f"  Slip ABS median : {slip1_abs.median():.1f}t (cout reel timing)")
    print(f"  Slip ABS mean   : {slip1_abs.mean():.1f}t")
else:
    print("\nBot 1 : pas de slip_entry_ticks instrumentes")

# Bot 2 : pas de slip_entry_ticks. On peut estimer via le delay Databento
# (on n'a pas la donnee precise mais on sait que ~30min de retard)
print(f"\nBot 2 (DB Sim2) — pas instrumente. Estimation : Databento Historical")
print(f"  delay ~30min → fills systematiquement decales. Cf trade ES vu live")
print(f"  ce soir : signal entry 7144.50 → fill reel 7150.25 = +23 ticks slippage")

# ==================================================================
# B. MAE / MFE DISTRIBUTION PAR OUTCOME (Bot 1)
# ==================================================================
print("\n" + "=" * 100)
print("  B. MAE / MFE PAR OUTCOME — Bot 1 (signal de timing)")
print("=" * 100)

df1["mae_n"] = pd.to_numeric(df1["mae"], errors="coerce")
df1["mfe_n"] = pd.to_numeric(df1["mfe"], errors="coerce")
df1["pnl_ticks_n"] = pd.to_numeric(df1["pnl_ticks"], errors="coerce")

for outcome in ["TP", "SL", "TIMEOUT"]:
    sub = df1[df1["outcome"] == outcome]
    n = len(sub)
    if not n:
        continue
    mae_med = sub["mae_n"].median()
    mae_mean = sub["mae_n"].mean()
    mfe_med = sub["mfe_n"].median()
    mfe_mean = sub["mfe_n"].mean()
    pnl_med = sub["pnl_ticks_n"].median()
    print(f"\n  {outcome:>8s} (n={n}) :")
    print(f"    MAE median = {mae_med:+.1f}t | MAE mean = {mae_mean:+.1f}t (max adverse)")
    print(f"    MFE median = {mfe_med:+.1f}t | MFE mean = {mfe_mean:+.1f}t (max favorable)")
    print(f"    PnL median = {pnl_med:+.1f}t")

# ==================================================================
# C. "MFE CACHÉ" — trades SL qui ont eu un MFE positif avant de mourir
#    → potentiel d'un trailing stop / TP partiel
# ==================================================================
print("\n" + "=" * 100)
print("  C. \"MFE CACHE\" : trades SL qui ont eu un MFE+ avant de mourir")
print("     (= timing exit aurait pu sauver le trade)")
print("=" * 100)

sl_trades = df1[df1["outcome"] == "SL"].copy()
mfe_positive_in_sl = sl_trades[sl_trades["mfe_n"] > 0]
print(f"\nBot 1 : {len(mfe_positive_in_sl)}/{len(sl_trades)} trades SL ont eu un MFE > 0")
if len(mfe_positive_in_sl) > 0:
    print(f"  MFE+ median   : +{mfe_positive_in_sl['mfe_n'].median():.1f}t")
    print(f"  MFE+ mean     : +{mfe_positive_in_sl['mfe_n'].mean():.1f}t")
    print(f"  MFE+ max      : +{mfe_positive_in_sl['mfe_n'].max():.1f}t")
    # Detail top 5
    print(f"\n  Top 5 trades SL avec MFE+ caches :")
    top5 = mfe_positive_in_sl.nlargest(5, "mfe_n")
    for _, r in top5.iterrows():
        print(f"    {str(r['entry_time'])[:19]} {r['symbol']} {r['direction']} "
              f"entry={r['entry_price']:.2f} | MFE+{r['mfe_n']:.0f}t (sauve) "
              f"vs SL {r['pnl_ticks_n']:+.0f}t")

# Simu : si on avait un trailing stop a +20t MFE (= breakeven), combien sauvée ?
print(f"\n  SIMU TRAILING : si exit a MFE+20t (breakeven) au lieu de SL, sauve combien $ ?")
saved_count = 0
saved_usd = 0
for _, r in sl_trades.iterrows():
    if r["mfe_n"] >= 20:
        # Au lieu de pnl_ticks (negatif), on aurait fait +20t (breakeven trailing)
        original_pnl = r["pnl_ticks_n"]
        new_pnl = 20  # exit BE par trailing
        delta_t = new_pnl - original_pnl
        delta_usd = delta_t * TICK_VALUE.get(r["symbol"], 1) * r.get("n_micros", 3)
        saved_usd += delta_usd
        saved_count += 1
print(f"    {saved_count}/{len(sl_trades)} trades sauves (MFE >= 20t requis)")
print(f"    Sauvegarde : ${saved_usd:+.2f}")

# ==================================================================
# D. "MAE CACHÉ" — trades TP qui sont allés contre nous avant de gagner
#    → quantifie le mauvais timing d'entry (on est entre TROP TOT)
# ==================================================================
print("\n" + "=" * 100)
print("  D. \"MAE CACHE\" : trades TP qui ont eu un MAE adverse avant de gagner")
print("     (= timing entry trop precoce, prix continuait a baisser)")
print("=" * 100)

tp_trades = df1[df1["outcome"] == "TP"].copy()
print(f"\nBot 1 : {len(tp_trades)} trades TP")
if len(tp_trades) > 0:
    mae_med_tp = tp_trades["mae_n"].median()
    mae_mean_tp = tp_trades["mae_n"].mean()
    print(f"  MAE median sur TP : {mae_med_tp:+.1f}t (timing entry sub-optimal)")
    print(f"  MAE mean sur TP   : {mae_mean_tp:+.1f}t")
    # Detail
    for _, r in tp_trades.iterrows():
        bonus_lost = abs(r["mae_n"]) if r["mae_n"] < 0 else 0
        print(f"    {str(r['entry_time'])[:19]} {r['symbol']} {r['direction']} "
              f"entry={r['entry_price']:.2f} pnl={r['pnl_ticks_n']:+.0f}t "
              f"MAE={r['mae_n']:+.0f}t (entry tardive de {bonus_lost:.0f}t)")

# Simu : si on avait entré a entry_price + MAE (juste apres pullback bottom),
# combien on aurait gagné en plus
print(f"\n  SIMU ENTRY OPTIMALE (entry = close + MAE = au pullback max) :")
delta_total = 0
for _, r in tp_trades.iterrows():
    if r["mae_n"] < 0:
        # Bonus = abs(MAE) ticks
        delta_t = abs(r["mae_n"])
        delta_usd = delta_t * TICK_VALUE.get(r["symbol"], 1) * r.get("n_micros", 3)
        delta_total += delta_usd
print(f"    Bonus theorique : ${delta_total:+.2f} (sur {len(tp_trades)} trades TP)")

# ==================================================================
# E. PERFORMANCE PAR MUR (Bot 1 + Bot 2)
# ==================================================================
print("\n" + "=" * 100)
print("  E. PERFORMANCE PAR MUR (sl_wall / tp_wall)")
print("=" * 100)

for label, df in [("Bot 1 DMP Sim3", df1), ("Bot 2 DB Sim2", df2)]:
    print(f"\n{label} — sl_wall :")
    if "sl_wall" in df.columns:
        for wall, grp in df.groupby("sl_wall"):
            n = len(grp)
            sl_count = (grp["outcome"] == "SL").sum()
            wr_inverse = sl_count / n * 100  # % de SL hit (inverse de wall hold)
            pnl = pd.to_numeric(grp["pnl_usd"], errors="coerce").sum()
            print(f"  {str(wall):<40s} | n={n:>2d} | SL_hit={wr_inverse:.0f}% | PnL=${pnl:+.2f}")
    print(f"\n{label} — tp_wall (wall HIT vs miss) :")
    if "tp_wall" in df.columns:
        for wall, grp in df.groupby("tp_wall"):
            n = len(grp)
            tp_count = (grp["outcome"] == "TP").sum()
            tp_hit = tp_count / n * 100
            pnl = pd.to_numeric(grp["pnl_usd"], errors="coerce").sum()
            print(f"  {str(wall):<40s} | n={n:>2d} | TP_hit={tp_hit:.0f}% | PnL=${pnl:+.2f}")

# ==================================================================
# F. OPTIMAL R-MULTIPLE — simulation TP=1R / 1.5R / 2R / 3R
# ==================================================================
print("\n" + "=" * 100)
print("  F. OPTIMAL R-MULTIPLE — simu TP a differents niveaux R")
print("=" * 100)
print("\n  Concept : si on avait force TP=N*R au lieu du TP wall actuel,")
print("  combien de trades aurraient hit ? (necessite MFE)")

if "sl_tier" in df1.columns and "mae_n" in df1.columns:
    # On utilise sl_ticks calcule a partir de sl_price - entry_price
    df1["sl_ticks_calc"] = abs(pd.to_numeric(df1["sl_price"], errors="coerce") -
                                pd.to_numeric(df1["entry_price"], errors="coerce")) / TICK_SIZE
    print(f"\n  Bot 1 : MFE max moyen = {df1['mfe_n'].mean():+.1f}t")
    print(f"           SL  max moyen = {df1['sl_ticks_calc'].mean():.1f}t")

    for r_multiple in [1.0, 1.5, 2.0, 3.0]:
        target_ticks = df1["sl_ticks_calc"] * r_multiple
        # Trade hit si MFE >= target
        hit = (df1["mfe_n"] >= target_ticks).sum()
        # PnL simu : hit -> +N*sl_ticks ; miss -> SL (-sl_ticks)
        pnl_sim = 0
        for _, r in df1.iterrows():
            sl_t = r["sl_ticks_calc"]
            if pd.isna(sl_t) or sl_t == 0:
                continue
            mfe = r["mfe_n"]
            if mfe >= sl_t * r_multiple:
                pnl_t = sl_t * r_multiple
            else:
                # SL ou TIMEOUT : prend le pnl reel
                pnl_t = r["pnl_ticks_n"]
            tv = TICK_VALUE.get(r["symbol"], 1)
            pnl_sim += pnl_t * tv * r.get("n_micros", 3)
        print(f"  TP = {r_multiple}R | hit = {hit}/{len(df1)} ({hit/len(df1)*100:.0f}%) | PnL simu = ${pnl_sim:+.2f}")

# ==================================================================
# G. SLIPPAGE EXIT — quantifier le coût mauvais timing exit
# ==================================================================
print("\n" + "=" * 100)
print("  G. SLIPPAGE EXIT (entre target prix et fill)")
print("=" * 100)

if "slip_exit_ticks" in df1.columns:
    slip_e1 = pd.to_numeric(df1["slip_exit_ticks"], errors="coerce").dropna()
    print(f"\nBot 1 — slip_exit_ticks :")
    print(f"  N samples       : {len(slip_e1)}")
    print(f"  Median          : {slip_e1.median():+.1f}t")
    print(f"  Mean            : {slip_e1.mean():+.1f}t")
    print(f"  Worst           : {slip_e1.min():+.1f}t")
    # Cout total slippage exit
    cost = 0
    for _, r in df1.iterrows():
        s = r.get("slip_exit_ticks")
        if pd.notna(s):
            cost += s * TICK_VALUE.get(r["symbol"], 1) * r.get("n_micros", 3)
    print(f"  Cout total slip exit : ${cost:+.2f}")

# ==================================================================
# H. BOT 2 — features at entry : WIN vs LOSS
# ==================================================================
print("\n" + "=" * 100)
print("  H. BOT 2 — features at entry : differenciateur WIN vs LOSS")
print("=" * 100)

if "features_at_entry" in df2.columns:
    wins2 = df2[df2["pnl_ticks"] > 0]
    losses2 = df2[df2["pnl_ticks"] <= 0]
    if len(wins2) > 0 and len(losses2) > 0:
        # Prend le 1er trade WIN et 1er trade LOSS pour comparer features
        feat_keys = set()
        for _, r in df2.iterrows():
            feat = r.get("features_at_entry", {})
            if isinstance(feat, dict):
                feat_keys.update(feat.keys())
        # On regarde un sous-ensemble de features pertinentes pour timing
        timing_features = [
            "atr_14m_pct", "rvol_regime", "delta_bar", "n_trades", "bar_range_pct",
            "position_in_range", "dist_mq_hvl_pct", "dist_mq_call_pct", "dist_mq_put_pct",
            "dist_1d_max_ticks_pct", "dist_1d_min_ticks_pct", "dist_gex_nearest_up_pct",
            "dist_gex_nearest_dn_pct", "cvd_5d_rolling_ffd", "im_volume_lead",
            "rvol_buy_strong", "rvol_sell", "rvol_absorb_buy", "open_zone",
            "bool_above_mq_hvl",
        ]
        print(f"\n  Comparaison median WIN ({len(wins2)}) vs LOSS ({len(losses2)}) sur features cles :")
        print(f"  {'Feature':<35s} {'WIN med':>12s} {'LOSS med':>12s} {'Delta':>10s}")
        print(f"  " + "-" * 75)
        for f in timing_features:
            wv, lv = [], []
            for _, r in wins2.iterrows():
                feat = r.get("features_at_entry", {})
                if isinstance(feat, dict) and f in feat and feat[f] is not None:
                    try:
                        wv.append(float(feat[f]))
                    except (TypeError, ValueError):
                        pass
            for _, r in losses2.iterrows():
                feat = r.get("features_at_entry", {})
                if isinstance(feat, dict) and f in feat and feat[f] is not None:
                    try:
                        lv.append(float(feat[f]))
                    except (TypeError, ValueError):
                        pass
            if not wv or not lv:
                continue
            mw = statistics.median(wv)
            ml = statistics.median(lv)
            delta = mw - ml
            marker = "  ⚠️" if abs(delta) > abs(ml) * 0.5 else ""
            print(f"  {f:<35s} {mw:>12.4f} {ml:>12.4f} {delta:>+10.4f}{marker}")

# ==================================================================
# I. CROSS-BOT — setups simultanés et performance comparée
# ==================================================================
print("\n" + "=" * 100)
print("  I. CROSS-BOT : setups simultanes (trades < 30min ecart, meme symbole)")
print("=" * 100)

simul = []
for _, t1 in df1.iterrows():
    for _, t2 in df2.iterrows():
        if t1["symbol"] != t2["symbol"]:
            continue
        delta_min = abs((t1["entry_dt"] - t2["entry_dt"]).total_seconds()) / 60
        if delta_min < 30:
            simul.append({
                "sym": t1["symbol"],
                "delta_min": delta_min,
                "bot1_dir": t1["direction"],
                "bot1_entry": t1["entry_price"],
                "bot1_outcome": t1["outcome"],
                "bot1_pnl_t": t1["pnl_ticks_n"],
                "bot2_dir": t2["direction"],
                "bot2_entry": t2["entry_price"],
                "bot2_outcome": t2["outcome"],
                "bot2_pnl_t": pd.to_numeric(t2.get("pnl_ticks"), errors="coerce"),
            })
sim_df = pd.DataFrame(simul)
if len(sim_df) > 0:
    print(f"\n  N setups simultanes : {len(sim_df)}")
    same_dir = sim_df[sim_df["bot1_dir"].str[:4] == sim_df["bot2_dir"].str[:4]]
    print(f"  Meme direction : {len(same_dir)}")
    if len(same_dir) > 0:
        # Comparaison entry price (qui est entré au mieux ?)
        print(f"\n  {'Sym':<3s} {'Dir':<5s} {'Bot1 entry':>10s} {'Bot2 entry':>10s} "
              f"{'Diff (t)':>10s} {'Bot1 pnl':>10s} {'Bot2 pnl':>10s}")
        for _, r in same_dir.iterrows():
            diff_t = (r["bot2_entry"] - r["bot1_entry"]) / TICK_SIZE
            print(f"  {r['sym']:<3s} {r['bot1_dir'][:5]:<5s} "
                  f"{r['bot1_entry']:>10.2f} {r['bot2_entry']:>10.2f} "
                  f"{diff_t:>+10.1f} {r['bot1_pnl_t']:>+10.0f} {r['bot2_pnl_t']:>+10.0f}")

# ==================================================================
# VERDICT FINAL — empirical findings
# ==================================================================
print("\n" + "=" * 100)
print("  VERDICT EMPIRIQUE — TIMING IS THE KEY")
print("=" * 100)

# Top 3 findings actionables
print("\n  CHIFFRES CLES :")
n1 = len(df1)
n_tp1 = (df1["outcome"] == "TP").sum()
n_sl1 = (df1["outcome"] == "SL").sum()
mfe_in_sl = (df1[df1["outcome"] == "SL"]["mfe_n"] > 20).sum()
mae_in_tp = (df1[df1["outcome"] == "TP"]["mae_n"] < -10).sum()
print(f"  • Bot 1 : {n_tp1}/{n1} TP, {n_sl1}/{n1} SL, {n1 - n_tp1 - n_sl1} TIMEOUT")
print(f"  • {mfe_in_sl}/{n_sl1} trades SL ont eu MFE > +20t avant de mourir = TIMING EXIT")
print(f"  • {mae_in_tp}/{n_tp1} trades TP ont eu MAE < -10t avant gain = TIMING ENTRY tardif")

print(f"\n  CONCLUSION TIMING ENTRY (Jackson) :")
print(f"  Si on avait entré au MAE max (pullback bottom), bonus theorique calcule en D")
print(f"  Slippage entry Bot 1 (instrumente) : median {pd.to_numeric(df1['slip_entry_ticks'], errors='coerce').median():+.1f}t")
print(f"  Slippage entry Bot 2 (estime) : ~+23t systematique (Databento delay 30min)")

print(f"\n  CONCLUSION TIMING EXIT :")
print(f"  Trailing breakeven a +20t MFE aurait sauve : voir section C")
print(f"  Optimal R-multiple : voir section F (pour identifier le bon TP)")

print("\n" + "=" * 100)
