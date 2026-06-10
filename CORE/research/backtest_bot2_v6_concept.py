"""Backtest MVP Concept Bot 2 V6 (range_fade + breakout) NQ avril+mai 2026."""
from __future__ import annotations
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import numpy as np
import pandas as pd
from CORE.range_detector_v3 import RangeDetectorV3

TICK_SIZE_NQ = 0.25
TICK_VALUE_NQ_MICRO = 0.50
ATR_PERIOD = 14
DENSITY_MIN = 2
RF_RANGE_POS_LOW = 0.20
RF_RANGE_POS_HIGH = 0.80
RF_SL_ATR_MULT = 1.5
RF_MAX_HOLD_MIN = 30
RF_SCALE_OUT_FRAC = 0.5
BO_VOL_MULT = 1.5
BO_AVG_VOL_LOOKBACK = 20
BO_CONFIRM_TICKS = 5
BO_SL_ATR_MULT = 1.0
BO_TP_RANGE_MULT = 2.0
BO_TRAIL_MFE_TRIGGER = 50
BO_TRAIL_STOP_BUFFER = 20
BO_MAX_HOLD_MIN = 60
RANGE_MACRO_MIN = 5
RANGE_AGE_MIN = 30
RTH_START_MIN = 13 * 60 + 30
RTH_END_MIN = 20 * 60

def atr_wilder_series(highs, lows, closes, n=14):
    nbars = len(highs)
    atr = np.full(nbars, np.nan)
    if nbars < n + 1:
        return atr
    tr = np.full(nbars, np.nan)
    tr[0] = highs[0] - lows[0]
    for i in range(1, nbars):
        tr[i] = max(highs[i] - lows[i], abs(highs[i] - closes[i-1]), abs(lows[i] - closes[i-1]))
    atr[n] = np.mean(tr[1:n+1])
    for i in range(n+1, nbars):
        atr[i] = (atr[i-1] * (n-1) + tr[i]) / n
    return atr


def load_and_normalize_nq():
    df_avr = pd.read_parquet("DATA/PAPER_TRADES_V6_AUDIT/nq_avr_v4.parquet")
    df_mai = pd.read_parquet("DATA/PAPER_TRADES_V6_AUDIT/nq_mai_v4_fresh.parquet")
    df_avr["ts_event"] = pd.to_datetime(df_avr["ts_event"])
    if df_avr["ts_event"].dt.tz is not None:
        df_avr["ts_event"] = df_avr["ts_event"].dt.tz_convert("UTC").dt.tz_localize(None)
    df_mai["ts_event"] = pd.to_datetime(df_mai["ts_event"])
    if df_mai["ts_event"].dt.tz is not None:
        df_mai["ts_event"] = df_mai["ts_event"].dt.tz_convert("UTC").dt.tz_localize(None)
    common = [c for c in df_avr.columns if c in df_mai.columns]
    df = pd.concat([df_avr[common], df_mai[common]], ignore_index=True)
    df = df.sort_values("ts_event").reset_index(drop=True)
    minutes = df["ts_event"].dt.hour * 60 + df["ts_event"].dt.minute
    df = df[(minutes >= RTH_START_MIN) & (minutes < RTH_END_MIN)].reset_index(drop=True)
    df["date"] = df["ts_event"].dt.date
    return df


def compute_range_features(df):
    print("[compute] V3 detect_iterative on " + str(len(df)) + " bars")
    det = RangeDetectorV3(sym="NQ", use_atr_macro=True, use_close_breakout=True)
    df_aug = det.detect_iterative(df)
    df_aug["atr_14"] = pd.Series(
        atr_wilder_series(df["high"].values, df["low"].values, df["close"].values, n=ATR_PERIOD),
        index=df_aug.index,
    )
    return df_aug


def compute_range_age_min(df):
    n_macro = df["n_macro_ok"].astype(int).values
    macro_5plus = n_macro >= RANGE_MACRO_MIN
    age = np.zeros(len(df), dtype=int)
    current = 0
    for i in range(len(df)):
        if macro_5plus[i]:
            current += 1
        else:
            current = 0
        age[i] = current
    return pd.Series(age, index=df.index)


def classify_mode(row):
    br = str(row.get("range_break_risk", "NONE"))
    if br in ("UP_BREAK_IMMINENT", "DOWN_BREAK_IMMINENT"):
        return "BREAKOUT"
    n_macro = int(row.get("n_macro_ok", 0) or 0)
    age = int(row.get("range_age_min", 0) or 0)
    if n_macro >= RANGE_MACRO_MIN and age >= RANGE_AGE_MIN:
        return "RANGE_FADE"
    return "NO_TRADE"


def simulate_range_fade(df, i):
    row = df.iloc[i]
    if pd.isna(row["range_low_zone"]) or pd.isna(row["range_high_zone"]):
        return None
    if pd.isna(row["atr_14"]) or row["atr_14"] <= 0:
        return None
    range_low = float(row["range_low_zone"])
    range_high = float(row["range_high_zone"])
    range_mid = (range_low + range_high) / 2.0
    range_pos = row["range_pos"]
    density_low = int(row.get("density_low", 0) or 0)
    density_high = int(row.get("density_high", 0) or 0)
    atr_pts = float(row["atr_14"])
    entry = float(row["close"])
    date = row["date"]
    if range_pos is not None and not pd.isna(range_pos) and range_pos < RF_RANGE_POS_LOW and density_low >= DENSITY_MIN:
        direction = "BUY"
        sl_price = range_low - RF_SL_ATR_MULT * atr_pts
        tp1_price = range_mid
        tp2_price = range_high - 1 * TICK_SIZE_NQ
    elif range_pos is not None and not pd.isna(range_pos) and range_pos > RF_RANGE_POS_HIGH and density_high >= DENSITY_MIN:
        direction = "SELL"
        sl_price = range_high + RF_SL_ATR_MULT * atr_pts
        tp1_price = range_mid
        tp2_price = range_low + 1 * TICK_SIZE_NQ
    else:
        return None
    if direction == "BUY" and (tp1_price <= entry or tp2_price <= entry or sl_price >= entry):
        return None
    if direction == "SELL" and (tp1_price >= entry or tp2_price >= entry or sl_price <= entry):
        return None
    half_size = RF_SCALE_OUT_FRAC
    tp1_hit = False
    pnl_ticks = 0.0
    exit_reason = "TIME"
    bars_held = 0
    end_idx = min(i + 1 + RF_MAX_HOLD_MIN, len(df))
    exited = False
    for j in range(i + 1, end_idx):
        bars_held += 1
        b_high = float(df.iloc[j]["high"])
        b_low = float(df.iloc[j]["low"])
        if direction == "BUY":
            if b_low <= sl_price:
                if tp1_hit:
                    sl_pnl = (sl_price - entry) / TICK_SIZE_NQ
                    pnl_ticks += sl_pnl * (1 - half_size)
                    exit_reason = "SL_AFTER_TP1"
                else:
                    sl_pnl = (sl_price - entry) / TICK_SIZE_NQ
                    pnl_ticks = sl_pnl
                    exit_reason = "SL"
                exited = True
                break
            if not tp1_hit and b_high >= tp1_price:
                tp1_pnl = (tp1_price - entry) / TICK_SIZE_NQ
                pnl_ticks += tp1_pnl * half_size
                tp1_hit = True
                sl_price = entry
            if tp1_hit and b_high >= tp2_price:
                tp2_pnl = (tp2_price - entry) / TICK_SIZE_NQ
                pnl_ticks += tp2_pnl * (1 - half_size)
                exit_reason = "TP2"
                exited = True
                break
        else:
            if b_high >= sl_price:
                if tp1_hit:
                    sl_pnl = (entry - sl_price) / TICK_SIZE_NQ
                    pnl_ticks += sl_pnl * (1 - half_size)
                    exit_reason = "SL_AFTER_TP1"
                else:
                    sl_pnl = (entry - sl_price) / TICK_SIZE_NQ
                    pnl_ticks = sl_pnl
                    exit_reason = "SL"
                exited = True
                break
            if not tp1_hit and b_low <= tp1_price:
                tp1_pnl = (entry - tp1_price) / TICK_SIZE_NQ
                pnl_ticks += tp1_pnl * half_size
                tp1_hit = True
                sl_price = entry
            if tp1_hit and b_low <= tp2_price:
                tp2_pnl = (entry - tp2_price) / TICK_SIZE_NQ
                pnl_ticks += tp2_pnl * (1 - half_size)
                exit_reason = "TP2"
                exited = True
                break
    if not exited:
        final_price = float(df.iloc[min(end_idx - 1, len(df) - 1)]["close"])
        if direction == "BUY":
            time_pnl = (final_price - entry) / TICK_SIZE_NQ
        else:
            time_pnl = (entry - final_price) / TICK_SIZE_NQ
        if tp1_hit:
            pnl_ticks += time_pnl * (1 - half_size)
            exit_reason = "TIME_AFTER_TP1"
        else:
            pnl_ticks = time_pnl
            exit_reason = "TIME"
    return {"mode": "RANGE_FADE", "direction": direction, "entry_idx": i, "entry_ts": row["ts_event"], "date": date, "entry_price": entry, "atr_pts": atr_pts, "range_pos": range_pos, "density_low": density_low, "density_high": density_high, "range_size_pts": range_high - range_low, "n_macro_ok": int(row.get("n_macro_ok", 0)), "range_age_min": int(row.get("range_age_min", 0)), "bars_held": bars_held, "exit_reason": exit_reason, "pnl_ticks": pnl_ticks, "pnl_usd": pnl_ticks * TICK_VALUE_NQ_MICRO}


def simulate_breakout(df, i):
    row = df.iloc[i]
    br = str(row.get("range_break_risk", "NONE"))
    if br not in ("UP_BREAK_IMMINENT", "DOWN_BREAK_IMMINENT"):
        return None
    if pd.isna(row["range_low_zone"]) or pd.isna(row["range_high_zone"]):
        return None
    if pd.isna(row["atr_14"]) or row["atr_14"] <= 0:
        return None
    if i < BO_AVG_VOL_LOOKBACK:
        return None
    avg_vol = float(df.iloc[i - BO_AVG_VOL_LOOKBACK: i]["volume"].mean())
    cur_vol = float(row["volume"])
    if cur_vol < BO_VOL_MULT * avg_vol:
        return None
    range_low = float(row["range_low_zone"])
    range_high = float(row["range_high_zone"])
    range_height_pts = range_high - range_low
    atr_pts = float(row["atr_14"])
    confirm_offset = BO_CONFIRM_TICKS * TICK_SIZE_NQ
    direction = "BUY" if br == "UP_BREAK_IMMINENT" else "SELL"
    if direction == "BUY":
        entry = range_high + confirm_offset
        if float(row["high"]) < entry:
            return None
        sl_price = entry - BO_SL_ATR_MULT * atr_pts
        tp_price = entry + BO_TP_RANGE_MULT * range_height_pts
    else:
        entry = range_low - confirm_offset
        if float(row["low"]) > entry:
            return None
        sl_price = entry + BO_SL_ATR_MULT * atr_pts
        tp_price = entry - BO_TP_RANGE_MULT * range_height_pts
    date = row["date"]
    pnl_ticks = 0.0
    exit_reason = "TIME"
    bars_held = 0
    trail_active = False
    trail_stop = None
    end_idx = min(i + 1 + BO_MAX_HOLD_MIN, len(df))
    exited = False
    for j in range(i + 1, end_idx):
        bars_held += 1
        b_high = float(df.iloc[j]["high"])
        b_low = float(df.iloc[j]["low"])
        if direction == "BUY":
            effective_sl = trail_stop if trail_active and trail_stop is not None else sl_price
            if b_low <= effective_sl:
                pnl_ticks = (effective_sl - entry) / TICK_SIZE_NQ
                exit_reason = "TRAIL_HIT" if trail_active else "SL"
                exited = True
                break
            if b_high >= tp_price:
                pnl_ticks = (tp_price - entry) / TICK_SIZE_NQ
                exit_reason = "TP"
                exited = True
                break
            mfe_ticks = (b_high - entry) / TICK_SIZE_NQ
            if mfe_ticks >= BO_TRAIL_MFE_TRIGGER:
                new_trail = b_high - BO_TRAIL_STOP_BUFFER * TICK_SIZE_NQ
                if not trail_active or new_trail > (trail_stop if trail_stop is not None else -1e9):
                    trail_stop = new_trail
                    trail_active = True
        else:
            effective_sl = trail_stop if trail_active and trail_stop is not None else sl_price
            if b_high >= effective_sl:
                pnl_ticks = (entry - effective_sl) / TICK_SIZE_NQ
                exit_reason = "TRAIL_HIT" if trail_active else "SL"
                exited = True
                break
            if b_low <= tp_price:
                pnl_ticks = (entry - tp_price) / TICK_SIZE_NQ
                exit_reason = "TP"
                exited = True
                break
            mfe_ticks = (entry - b_low) / TICK_SIZE_NQ
            if mfe_ticks >= BO_TRAIL_MFE_TRIGGER:
                new_trail = b_low + BO_TRAIL_STOP_BUFFER * TICK_SIZE_NQ
                if not trail_active or new_trail < (trail_stop if trail_stop is not None else 1e9):
                    trail_stop = new_trail
                    trail_active = True
    if not exited:
        final_price = float(df.iloc[min(end_idx - 1, len(df) - 1)]["close"])
        if direction == "BUY":
            pnl_ticks = (final_price - entry) / TICK_SIZE_NQ
        else:
            pnl_ticks = (entry - final_price) / TICK_SIZE_NQ
        exit_reason = "TIME"
    return {"mode": "BREAKOUT", "direction": direction, "entry_idx": i, "entry_ts": row["ts_event"], "date": date, "entry_price": entry, "atr_pts": atr_pts, "range_size_pts": range_height_pts, "vol_ratio": cur_vol / avg_vol if avg_vol > 0 else 0, "break_risk": br, "bars_held": bars_held, "exit_reason": exit_reason, "trail_active": trail_active, "pnl_ticks": pnl_ticks, "pnl_usd": pnl_ticks * TICK_VALUE_NQ_MICRO, "density_low": 0, "density_high": 0, "range_pos": row.get("range_pos"), "n_macro_ok": int(row.get("n_macro_ok", 0)), "range_age_min": int(row.get("range_age_min", 0))}


def main():
    print("=" * 80)
    print("BACKTEST MVP CONCEPT BOT 2 V6 (range_fade + breakout) NQ avril+mai 2026")
    print("=" * 80)
    df = load_and_normalize_nq()
    print("[1] Loaded " + str(len(df)) + " bars NQ US RTH, days=" + str(df["date"].nunique()))
    print("    Days: " + str(sorted(df["date"].unique())))
    df_aug = compute_range_features(df)
    df_aug["range_age_min"] = compute_range_age_min(df_aug)
    is_range_pct = round(df_aug["is_range_macro"].mean() * 100, 1)
    macro5_pct = round((df_aug["n_macro_ok"] >= 5).mean() * 100, 1)
    br_up = int((df_aug["range_break_risk"] == "UP_BREAK_IMMINENT").sum())
    br_dn = int((df_aug["range_break_risk"] == "DOWN_BREAK_IMMINENT").sum())
    print("[2] V3 features. is_range_macro=" + str(is_range_pct) + "%  macro>=5=" + str(macro5_pct) + "%  break_risk_UP=" + str(br_up) + "  break_risk_DN=" + str(br_dn))
    df_aug["mode"] = df_aug.apply(classify_mode, axis=1)
    mode_counts = df_aug["mode"].value_counts()
    print("[3] Mode distribution (bars):")
    for m, n in mode_counts.items():
        print("    " + str(m) + ": " + str(n) + " (" + str(round(n/len(df_aug)*100, 1)) + "%)")
    print("[4] Mode pct par jour:")
    by_day = df_aug.groupby("date")["mode"].value_counts(normalize=True).unstack(fill_value=0) * 100
    print(by_day.round(1).to_string())
    trades = []
    cooldown_until_idx = 0
    for i in range(len(df_aug)):
        mode = df_aug.iloc[i]["mode"]
        if mode == "NO_TRADE":
            continue
        if i < cooldown_until_idx:
            continue
        trade = None
        if mode == "RANGE_FADE":
            trade = simulate_range_fade(df_aug, i)
        elif mode == "BREAKOUT":
            trade = simulate_breakout(df_aug, i)
        if trade is not None:
            trades.append(trade)
            cooldown_until_idx = i + trade["bars_held"] + 5
    print("")
    print("[5] " + str(len(trades)) + " trades simules au total")
    if not trades:
        print("ERREUR: 0 trade simule")
        return
    df_tr = pd.DataFrame(trades)
    print("")
    print("=" * 80)
    print("RESULTATS PAR MODE")
    print("=" * 80)
    for mode_name in ["RANGE_FADE", "BREAKOUT"]:
        sub = df_tr[df_tr["mode"] == mode_name]
        if len(sub) == 0:
            print("")
            print(mode_name + ": 0 trades")
            continue
        wins = sub[sub["pnl_ticks"] > 0]
        losses = sub[sub["pnl_ticks"] <= 0]
        gross_win = wins["pnl_ticks"].sum()
        gross_loss = abs(losses["pnl_ticks"].sum())
        pf = (gross_win / gross_loss) if gross_loss > 0 else float("inf")
        wr = len(wins) / len(sub) * 100 if len(sub) > 0 else 0
        avg_win = wins["pnl_ticks"].mean() if len(wins) > 0 else 0
        avg_loss = losses["pnl_ticks"].mean() if len(losses) > 0 else 0
        ev = sub["pnl_ticks"].mean()
        total_usd = sub["pnl_usd"].sum()
        cum = sub.sort_values("entry_ts")["pnl_ticks"].cumsum().values
        peak = np.maximum.accumulate(cum)
        dd = cum - peak
        max_dd = dd.min() if len(dd) > 0 else 0
        print("")
        print(mode_name + ":")
        print("  n trades : " + str(len(sub)))
        print("  WR       : " + str(round(wr, 1)) + "% (" + str(len(wins)) + " W / " + str(len(losses)) + " L)")
        if pf != float("inf"):
            print("  PF       : " + str(round(pf, 2)))
        else:
            print("  PF       : inf (0 losses)")
        print("  EV/trade : " + str(round(ev, 2)) + " ticks ($" + str(round(ev * TICK_VALUE_NQ_MICRO, 2)) + ")")
        print("  Avg W    : " + str(round(avg_win, 1)) + "t    Avg L : " + str(round(avg_loss, 1)) + "t")
        print("  Total    : " + str(round(sub["pnl_ticks"].sum(), 1)) + "t ($" + str(round(total_usd, 2)) + ")")
        print("  Max DD   : " + str(round(max_dd, 1)) + "t ($" + str(round(max_dd * TICK_VALUE_NQ_MICRO, 2)) + ")")
        print("  Exits    : " + str(sub["exit_reason"].value_counts().to_dict()))
        print("  Direction: " + str(sub["direction"].value_counts().to_dict()))
    print("")
    print("=" * 80)
    print("TOTAL COMBINED")
    print("=" * 80)
    wins = df_tr[df_tr["pnl_ticks"] > 0]
    losses = df_tr[df_tr["pnl_ticks"] <= 0]
    gross_win = wins["pnl_ticks"].sum()
    gross_loss = abs(losses["pnl_ticks"].sum())
    pf_str = str(round(gross_win / gross_loss, 2)) if gross_loss > 0 else "inf"
    wr = len(wins) / len(df_tr) * 100
    ev = df_tr["pnl_ticks"].mean()
    print("  n trades : " + str(len(df_tr)))
    print("  WR       : " + str(round(wr, 1)) + "%")
    print("  PF       : " + pf_str)
    print("  EV/trade : " + str(round(ev, 2)) + "t ($" + str(round(ev * TICK_VALUE_NQ_MICRO, 2)) + ")")
    print("  Total    : " + str(round(df_tr["pnl_ticks"].sum(), 1)) + "t ($" + str(round(df_tr["pnl_usd"].sum(), 2)) + ")")
    print("  Days     : " + str(df_tr["date"].nunique()) + ", trades/day = " + str(round(len(df_tr) / df_tr["date"].nunique(), 1)))
    print("")
    print("  PnL par jour:")
    daily = df_tr.groupby("date").agg(n=("pnl_ticks", "count"), pnl_ticks=("pnl_ticks", "sum"))
    daily["pnl_usd"] = daily["pnl_ticks"] * TICK_VALUE_NQ_MICRO
    print(daily.to_string())
    print("")
    print("=" * 80)
    print("ECHECS TYPIQUES")
    print("=" * 80)
    rf = df_tr[df_tr["mode"] == "RANGE_FADE"]
    if len(rf) > 0:
        sl_no_tp1 = rf[rf["exit_reason"] == "SL"]
        sl_after_tp1 = rf[rf["exit_reason"] == "SL_AFTER_TP1"]
        print("  RANGE_FADE : " + str(len(sl_no_tp1)) + "/" + str(len(rf)) + " SL avant TP1 (fake range)")
        print("               " + str(len(sl_after_tp1)) + "/" + str(len(rf)) + " SL apres TP1 (BE)")
    bo = df_tr[df_tr["mode"] == "BREAKOUT"]
    if len(bo) > 0:
        fake_bo = bo[bo["exit_reason"] == "SL"]
        print("  BREAKOUT   : " + str(len(fake_bo)) + "/" + str(len(bo)) + " fakeouts")
    out_path = "DATA/PAPER_TRADES_V6_AUDIT/_concept_bot2_v6_trades.csv"
    df_tr.to_csv(out_path, index=False)
    print("")
    print("  Saved: " + out_path)


if __name__ == "__main__":
    main()
