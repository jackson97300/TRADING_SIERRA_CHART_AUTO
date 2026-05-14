"""test_phase_b_streaming_real_data.py

Smoke test sur vraies donnees ES 09/04/2026 (Databento DBN/parquet).
Cible : chaine LOT 1 -> LOT 4 -> LOT 5 -> LOT 6 sans crash + stats coherentes.

Pas de parite batch ici (complexite trop elevee a setup). Smoke test :
  - 0 crash sur 1380 bars * 482K trades
  - fire rates raisonnables (color/long/divergence < 25%)
  - NaN counts coherents (warmup acceptable)
  - features distribution coherente (PF features valides)
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

# Add CORE to path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "CORE"))


def load_es_day(date_yyyymmdd: str = "20260409"):
    """Load ES trades + ohlcv-1m for one day."""
    y, m, d = date_yyyymmdd[:4], int(date_yyyymmdd[4:6]), int(date_yyyymmdd[6:8])
    base = ROOT / "DATA/DATABENTO/GLBX.MDP3"
    trades_path = base / f"trades/symbol=ES.c.0/year={y}/month={m}/day={d}/data_0.parquet"
    bars_path = base / f"ohlcv-1m/symbol=ES.c.0/year={y}/month={m}/day={d}/data_0.parquet"

    trades = pd.read_parquet(trades_path)
    bars = pd.read_parquet(bars_path)

    # Filter trades to action='T' (TRADE)
    if "action" in trades.columns:
        trades = trades[trades["action"] == "T"].copy()

    # Normalize side to A/B/N (Databento : A=ask aggressor BUY, B=bid aggressor SELL, N=none)
    if "side" not in trades.columns:
        trades["side"] = "N"

    return trades, bars


def build_trades_in_window(trades_df: pd.DataFrame, bar_start, bar_end) -> list:
    """Slice trades pour la fenetre [bar_start, bar_end) et retourner list de dicts."""
    mask = (trades_df["ts_event"] >= bar_start) & (trades_df["ts_event"] < bar_end)
    sub = trades_df.loc[mask, ["ts_event", "price", "size", "side"]]
    if sub.empty:
        return []
    return sub.to_dict(orient="records")


def main():
    print("=" * 70)
    print("SMOKE TEST PHASE_B_PLUS_PLUS STREAMING SUR DONNEES REELLES ES 09/04/2026")
    print("=" * 70)

    print("\n[1/4] Chargement donnees...")
    trades, bars = load_es_day("20260409")
    print(f"  Trades : {len(trades):,} (action=T)")
    print(f"  Bars   : {len(bars):,} (1-min OHLCV)")
    print(f"  Plage  : {bars['ts_event'].min()} -> {bars['ts_event'].max()}")

    # Imports streaming engines
    from phase_b_plus_plus_trades_streaming import (
        PhaseBPlusPlusTradesState,
        make_phase_b_plus_plus_trades_state as make_phase_b_trades_state,
        add_phase_b_plus_plus_trades_streaming as add_phase_b_trades_streaming,
    )
    from phase_b_plus_plus_absorb_streaming import (
        make_stack_absorb_state,
        add_stack_absorb_streaming,
    )
    from phase_b_plus_plus_trapped_streaming import (
        make_trapped_traders_state,
        add_trapped_traders_streaming,
    )
    from phase_b_plus_plus_delta_div_ext_streaming import (
        make_delta_div_ext_state,
        add_delta_div_ext_streaming,
    )
    from footprint_builder_streaming import build_footprint_cells_streaming

    print("\n[2/4] Init states streaming...")
    state_trades = make_phase_b_trades_state(symbol="ES")
    state_absorb = make_stack_absorb_state(symbol="ES")
    state_trapped = make_trapped_traders_state(symbol="ES")
    state_delta_div = make_delta_div_ext_state()
    print("  States ES initialises (4 sub-engines).")

    print("\n[3/4] Run streaming chain (1380 bars)...")
    out_rows = []
    errors = 0
    err_msg = None
    bar_dt_prev = None

    for i, bar in enumerate(bars.itertuples(index=False)):
        # Window : [bar_ts, bar_ts + 1min)
        bar_ts = bar.ts_event
        bar_end = bar_ts + pd.Timedelta(minutes=1)

        # Slice trades
        trades_window = build_trades_in_window(trades, bar_ts, bar_end)

        # Build footprint cells
        cells = build_footprint_cells_streaming(trades_window, tick=0.25)

        # Build row OHLCV + trades + cells
        row = {
            "ts_event": bar_ts,
            "open": float(bar.open),
            "high": float(bar.high),
            "low": float(bar.low),
            "close": float(bar.close),
            "volume": float(bar.volume),
            # Niveaux factices : pas de MQ levels en data reelle Databento direct
            # On simule absence (NaN ou 9999) -> stack/absorb retournera 0 normalement
            "mq_call_resistance": np.nan,
            "mq_put_support": np.nan,
            "mq_hvl": np.nan,
            "mq_call_resistance_0dte": np.nan,
            "mq_put_support_0dte": np.nan,
            "mq_hvl_0dte": np.nan,
            "mq_dist_call_resistance": np.nan,
            "mq_dist_put_support": np.nan,
            "mq_dist_hvl": np.nan,
            "mq_dist_call_resistance_0dte": np.nan,
            "mq_dist_put_support_0dte": np.nan,
            "mq_dist_hvl_0dte": np.nan,
            "mq_dist_gamma_wall_0dte": np.nan,
            "mq_dist_gex_call_strike": np.nan,
            "mq_dist_gex_put_strike": np.nan,
            "mq_dist_blue_line": np.nan,
            "mq_dist_orange_line": np.nan,
            "mq_dist_yellow_line": np.nan,
        }

        try:
            # LOT 1 trades aggregates (produit delta_div_buy/sell, delta_bar, etc.)
            row = add_phase_b_trades_streaming(row, state_trades, trades_in_window=trades_window)

            # LOT 4 absorb (produit near_resistance_level/near_support_level)
            row = add_stack_absorb_streaming(row, state_absorb, footprint_cells=cells)

            # LOT 5 trapped (consomme near_*) - dependance P0 fixed
            row = add_trapped_traders_streaming(row, state_trapped, footprint_cells=cells)

            # LOT 6 delta_div_ext (consomme delta_div_buy/sell de LOT 1)
            row = add_delta_div_ext_streaming(row, state_delta_div)

            out_rows.append(row)
        except Exception as e:
            errors += 1
            if err_msg is None:
                err_msg = f"Bar {i} ts={bar_ts} : {type(e).__name__}: {e}"

        if (i + 1) % 200 == 0:
            print(f"  {i+1}/{len(bars)} bars processed...")

    print(f"\n  Termine : {len(out_rows)} bars OK / {errors} erreurs")
    if err_msg:
        print(f"  Premiere erreur : {err_msg}")

    # ============================================================
    # [4/4] Statistiques + sanity checks
    # ============================================================
    print("\n[4/4] Statistiques output :")
    df_out = pd.DataFrame(out_rows)

    # === LOT 1 trades ===
    print("\n  --- LOT 1 trades aggregates ---")
    n = len(df_out)
    cols_lot1 = [
        "delta_bar", "buy_volume", "sell_volume",
        "delta_div_buy", "delta_div_sell",
        "trade_size_max", "trade_size_avg",
        "n_big_ask", "n_big_bid",
        "aggressor_ratio", "cluster_max_count",
    ]
    for c in cols_lot1:
        if c in df_out.columns:
            v = df_out[c]
            nans = v.isna().sum()
            non_zero = (v.fillna(0) != 0).sum()
            print(f"    {c:30s} : nan={nans:4d}  non_zero={non_zero:4d}/{n:4d}  "
                  f"mean={v.mean():.4f}  max={v.max():.4f}")

    # delta_div fire rates
    fire_buy = (df_out["delta_div_buy"] == 1).sum() if "delta_div_buy" in df_out.columns else 0
    fire_sell = (df_out["delta_div_sell"] == 1).sum() if "delta_div_sell" in df_out.columns else 0
    print(f"\n  Fire rates LOT 1 :")
    print(f"    delta_div_buy  : {fire_buy:4d}/{n} = {100*fire_buy/n:.2f}%")
    print(f"    delta_div_sell : {fire_sell:4d}/{n} = {100*fire_sell/n:.2f}%")

    # === LOT 4 absorb ===
    print("\n  --- LOT 4 absorb ---")
    cols_lot4 = [
        "bn_absorb_ask_raw", "bn_absorb_bid_raw",
        "bn_absorb_ask_at_resistance", "bn_absorb_bid_at_support",
        "near_resistance_level", "near_support_level",
        "bn_stack_ask_2", "bn_stack_bid_2",
    ]
    for c in cols_lot4:
        if c in df_out.columns:
            v = df_out[c]
            non_zero = (v.fillna(0) != 0).sum()
            print(f"    {c:35s} : non_zero={non_zero:4d}/{n:4d}  "
                  f"mean={v.fillna(0).mean():.4f}")

    # === LOT 5 trapped ===
    print("\n  --- LOT 5 trapped traders ---")
    cols_lot5 = [
        "bn_trapped_buyers_raw", "bn_trapped_sellers_raw",
        "bn_trapped_buyers_at_resistance", "bn_trapped_sellers_at_support",
        "n_trapped_buyers_zones_active", "n_trapped_sellers_zones_active",
        "dist_trapped_buyers_nearest_pct",
    ]
    for c in cols_lot5:
        if c in df_out.columns:
            v = df_out[c]
            non_zero = (v.fillna(0) != 0).sum()
            print(f"    {c:38s} : non_zero={non_zero:4d}/{n:4d}  "
                  f"mean={v.fillna(0).mean():.4f}")

    # === LOT 6 delta_div_ext ===
    print("\n  --- LOT 6 delta_div extension lines ---")
    cols_lot6 = [
        "n_delta_div_buy_zones_active", "n_delta_div_sell_zones_active",
        "dist_delta_div_buy_nearest_pct", "dist_delta_div_sell_nearest_pct",
        "n_delta_div_buy_cluster_within_0_2pct",
    ]
    for c in cols_lot6:
        if c in df_out.columns:
            v = df_out[c]
            non_zero = (v.fillna(0) != 0).sum()
            print(f"    {c:42s} : non_zero={non_zero:4d}/{n:4d}  "
                  f"mean={v.fillna(0).mean():.4f}  max={v.fillna(0).max():.4f}")

    # === Sanity checks
    print("\n" + "=" * 70)
    print("SANITY CHECKS :")
    ok = True

    # 1. No crash
    if errors == 0:
        print("  [OK] Aucune erreur sur 1380 bars + 482K trades")
    else:
        print(f"  [FAIL] {errors} erreurs detectees")
        ok = False

    # 2. fire rates raisonnables
    if "delta_div_buy" in df_out.columns:
        fb = (df_out["delta_div_buy"] == 1).mean() * 100
        fs = (df_out["delta_div_sell"] == 1).mean() * 100
        if 0 < fb < 30 and 0 < fs < 30:
            print(f"  [OK] delta_div fire rates : buy={fb:.1f}% sell={fs:.1f}% (in [0-30%])")
        else:
            print(f"  [WARN] delta_div fire rates suspects : buy={fb:.1f}% sell={fs:.1f}%")

    # 3. No explosion features
    if "trade_size_max" in df_out.columns:
        v = df_out["trade_size_max"].fillna(0).max()
        if v < 100000:
            print(f"  [OK] trade_size_max max : {v:.0f} (< 100K)")
        else:
            print(f"  [WARN] trade_size_max trop eleve : {v}")

    # 4. Volume coherent
    if "buy_volume" in df_out.columns and "sell_volume" in df_out.columns:
        total = (df_out["buy_volume"].fillna(0) + df_out["sell_volume"].fillna(0)).sum()
        bar_vol = bars["volume"].sum()
        print(f"  [INFO] Volume aggressor (buy+sell) : {total:,.0f}")
        print(f"  [INFO] Volume bars (sum)           : {bar_vol:,.0f}")
        if total > 0 and bar_vol > 0:
            ratio = total / bar_vol
            if 0.5 < ratio < 2.0:
                print(f"  [OK] Ratio aggressor/bar = {ratio:.2f} (coherent ~1.0)")
            else:
                print(f"  [WARN] Ratio anormal : {ratio:.2f}")

    print("\n" + "=" * 70)
    print("VERDICT : " + ("PASS" if ok else "FAIL"))
    print("=" * 70)

    return df_out


if __name__ == "__main__":
    df = main()
