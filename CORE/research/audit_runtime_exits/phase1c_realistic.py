"""
Phase 1c — Strategies realistes basees sur MFE absolu
"""
import pandas as pd, numpy as np
df = pd.read_pickle("D:/TRADING_SIERRA_CHART_AUTO/CORE/research/audit_runtime_exits/trades_bot1.pkl")

print(f"N trades = {len(df)} (NQ={len(df[df.symbol=='NQ'])} ES={len(df[df.symbol=='ES'])})")
print(f"Tick value : ES=$1.25 NQ=$0.50 -> per-trade pnl deja en ticks")
print()

# Note: pour standardiser, separons ES vs NQ car SL/TP en ticks tres differents
def report(df_sub, label):
    n = len(df_sub)
    pnl_base = df_sub['pnl_ticks'].sum()
    wr_base = (df_sub['pnl_ticks'] > 0).mean()
    print(f"\n=== {label}  N={n} ===")
    print(f"Baseline: PnL={pnl_base:+5.0f}t WR={wr_base*100:.0f}%")

    # Strategy A: BE move @ +X ticks (absolu)
    print("\n  -- Strat A: BE move @ MFE >= X ticks (exit BE si pas atteint TP) --")
    for thr_t in [10, 15, 20, 25, 30, 40]:
        # Si MFE >= thr_t : si TP atteint -> capture TP ; sinon -> BE (=0)
        pnl_be = np.where(
            df_sub['mfe'] >= thr_t,
            np.where(df_sub['mfe_pct_tp'] >= 1.0, df_sub['tp_dist_ticks'], 0.0),
            df_sub['pnl_ticks']
        )
        n_armed = (df_sub['mfe'] >= thr_t).sum()
        n_saved = ((df_sub['mfe'] >= thr_t) & (df_sub['pnl_ticks'] < 0)).sum()
        delta = pnl_be.sum() - pnl_base
        wr = (pnl_be > 0).mean()
        print(f"    thr={thr_t:3d}t  N_armed={n_armed:2d}  PnL={pnl_be.sum():+5.0f}t  delta={delta:+5.0f}t  WR={wr*100:.0f}%  saved_loss={n_saved}")

    # Strategy B: Partial 50% @ +X ticks (50% capturent, 50% reste avec stop @ entry)
    print("\n  -- Strat B: Partial 50% @ MFE >= X ticks (reste @ BE) --")
    for thr_t in [15, 20, 25, 30, 40, 50]:
        # 50% lock @ thr_t. 50% restant : BE si retrace, TP si continue
        def hypo(row, thr=thr_t):
            if row['mfe'] < thr:
                return row['pnl_ticks']
            half = 0.5 * thr  # 50% lock at +thr
            if row['mfe_pct_tp'] >= 1.0:
                # le restant capture TP_dist
                return half + 0.5 * row['tp_dist_ticks']
            else:
                # restant ramene a BE
                return half + 0.0
        pnl_partial = df_sub.apply(hypo, axis=1)
        n_armed = (df_sub['mfe'] >= thr_t).sum()
        delta = pnl_partial.sum() - pnl_base
        wr = (pnl_partial > 0).mean()
        print(f"    thr={thr_t:3d}t  N_armed={n_armed:2d}  PnL={pnl_partial.sum():+5.0f}t  delta={delta:+5.0f}t  WR={wr*100:.0f}%")

    # Strategy C: trailing @ +X ticks then trail by Y ticks
    # Approx : si MFE >= thr, et MFE > Y2*thr, capture MFE - Y2*thr_pullback
    print("\n  -- Strat C: Trail apres MFE >= X (give back Y ticks) --")
    for thr_t, give_back in [(20, 10), (25, 12), (30, 15), (40, 20), (50, 25)]:
        def hypo_trail(row, thr=thr_t, gb=give_back):
            if row['mfe'] < thr:
                return row['pnl_ticks']
            # Si MFE >= thr_t et TP atteint -> TP (ou trail final)
            if row['mfe_pct_tp'] >= 1.0:
                return row['tp_dist_ticks']
            # sinon : capture (MFE - give_back)
            return max(thr_t - gb, row['mfe'] - gb)  # au moins le thr-gb
        pnl_trail = df_sub.apply(hypo_trail, axis=1)
        delta = pnl_trail.sum() - pnl_base
        wr = (pnl_trail > 0).mean()
        n_armed = (df_sub['mfe'] >= thr_t).sum()
        print(f"    thr={thr_t:3d}t  give_back={give_back:2d}t  N_armed={n_armed:2d}  PnL={pnl_trail.sum():+5.0f}t  delta={delta:+5.0f}t  WR={wr*100:.0f}%")

# All
report(df, "ALL (ES+NQ)")
report(df[df.symbol=='NQ'], "NQ only")
report(df[df.symbol=='ES'], "ES only")
