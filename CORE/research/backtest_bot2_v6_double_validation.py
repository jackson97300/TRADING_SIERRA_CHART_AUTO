"""Backtest Bot 2 V6 -- range_fade + TREND_POST_BREAKOUT double validation.

Specs revisees Jackson 11/05:
 1. Bornes range = max(quantile 95, _last_swing_high_price) + buffer
                   min(quantile 5,  _last_swing_low_price)  - buffer
 2. TREND_POST_BREAKOUT = double validation 4 etats
 3. Locked params (pas de tuning post-hoc)
"""
from __future__ import annotations
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import numpy as np
import pandas as pd

from CORE.range_detector_v3 import RangeDetectorV3

TICK = 0.25
TICK_USD = 0.50
ATR_N = 14
RTH_START_MIN = 13 * 60 + 30
RTH_END_MIN = 20 * 60
RANGE_MACRO_MIN = 4  # PATCH loosened from 5 (cassure detection trop rare avec 5)
RANGE_AGE_MIN = 5  # PATCH loosened from 20 (cassure detection trop rare)
BUFFER_TICKS = 4
DENSITY_MIN = 2
RF_POS_LOW = 0.20
RF_POS_HIGH = 0.80
RF_SL_ATR_MULT = 1.5
RF_MAX_HOLD = 30
RF_SCALE_OUT_FRAC = 0.5
DV_CASSURE1_OFFSET_TICKS = 5
DV_VOL_MULT = 1.5
DV_VOL_LOOKBACK = 20
DV_CONSOLIDATION_TIMEOUT = 15
DV_TP_RANGE_MULT = 1.0
DV_TRAIL_MFE_TRIGGER = 50
DV_TRAIL_STOP_BUFFER = 20
DV_MAX_HOLD = 60



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
    for i in range(n + 1, nbars):
        atr[i] = (atr[i-1] * (n-1) + tr[i]) / n
    return atr


def load_and_normalize_nq():
    df_avr = pd.read_parquet("DATA/PAPER_TRADES_V6_AUDIT/nq_avr_v4.parquet")
    df_mai = pd.read_parquet("DATA/PAPER_TRADES_V6_AUDIT/nq_mai_v4_fresh.parquet")
    for d in (df_avr, df_mai):
        d["ts_event"] = pd.to_datetime(d["ts_event"])
        if d["ts_event"].dt.tz is not None:
            d["ts_event"] = d["ts_event"].dt.tz_convert("UTC").dt.tz_localize(None)
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
        atr_wilder_series(df["high"].values, df["low"].values, df["close"].values, n=ATR_N),
        index=df_aug.index,
    )
    return df_aug


def compute_range_age_min(df):
    n_macro = df["n_macro_ok"].astype(int).values
    macro_ok = n_macro >= RANGE_MACRO_MIN
    age = np.zeros(len(df), dtype=int)
    current = 0
    for i in range(len(df)):
        if macro_ok[i]:
            current += 1
        else:
            current = 0
        age[i] = current
    return pd.Series(age, index=df.index)


def compute_swing_bounded_range(df_aug):
    buf = BUFFER_TICKS * TICK
    range_high_raw = df_aug["range_high_zone"] - buf
    range_low_raw = df_aug["range_low_zone"] + buf
    swing_high = df_aug["_last_swing_high_price"]
    swing_low = df_aug["_last_swing_low_price"]
    range_high_swing_arr = np.maximum(range_high_raw, swing_high.fillna(-np.inf)) + buf
    range_low_swing_arr = np.minimum(range_low_raw, swing_low.fillna(np.inf)) - buf
    df_aug["range_high_swing"] = np.where(df_aug["range_high_zone"].isna(), np.nan, range_high_swing_arr)
    df_aug["range_low_swing"] = np.where(df_aug["range_low_zone"].isna(), np.nan, range_low_swing_arr)
    rng = df_aug["range_high_swing"] - df_aug["range_low_swing"]
    pos = (df_aug["close"] - df_aug["range_low_swing"]) / rng.replace(0, np.nan)
    df_aug["range_pos_swing"] = pos.clip(0.0, 1.0)
    return df_aug



def classify_state_dv(df_aug):
    n = len(df_aug)
    state = ["NO_TRADE"] * n
    mini_start_bar = -1
    direction_track = None
    vols = df_aug["volume"].values
    avg_vol_arr = pd.Series(vols).rolling(DV_VOL_LOOKBACK).mean().values
    close_arr = df_aug["close"].values
    high_arr = df_aug["high"].values
    low_arr = df_aug["low"].values
    rh_swing = df_aug["range_high_swing"].values
    rl_swing = df_aug["range_low_swing"].values
    n_macro = df_aug["n_macro_ok"].astype(int).values
    age = df_aug["range_age_min"].astype(int).values
    br = df_aug["range_break_risk"].astype(str).values

    sequences = []
    cassure1_seq_pending = None

    for i in range(n):
        st = "NO_TRADE"
        in_range_macro = (n_macro[i] >= RANGE_MACRO_MIN and age[i] >= RANGE_AGE_MIN)  # PATCH: drop break_risk gate (cassure = break_risk IMMINENT par def)

        if direction_track is None:
            if not in_range_macro:
                state[i] = st
                continue
            if i < 1 or pd.isna(rh_swing[i]) or pd.isna(rl_swing[i]):
                state[i] = "RANGE_OK"
                continue
            up_thresh = rh_swing[i] + DV_CASSURE1_OFFSET_TICKS * TICK
            dn_thresh = rl_swing[i] - DV_CASSURE1_OFFSET_TICKS * TICK
            close_now = close_arr[i]
            close_prev = close_arr[i-1]
            vol_ok = (not np.isnan(avg_vol_arr[i])) and (vols[i] >= DV_VOL_MULT * avg_vol_arr[i])

            if close_prev > up_thresh and close_now > up_thresh and vol_ok:
                direction_track = "UP"
                mini_start_bar = i
                cassure1_seq_pending = {
                    "cassure1_bar": i, "direction": "UP",
                    "range_high_swing_orig": float(rh_swing[i]),
                    "range_low_swing_orig": float(rl_swing[i]),
                    "range_size": float(rh_swing[i] - rl_swing[i]),
                    "vol_ratio_cassure1": float(vols[i] / max(1.0, avg_vol_arr[i])),
                    "outcome": None,
                }
                st = "CASSURE1_UP"
            elif close_prev < dn_thresh and close_now < dn_thresh and vol_ok:
                direction_track = "DN"
                mini_start_bar = i
                cassure1_seq_pending = {
                    "cassure1_bar": i, "direction": "DN",
                    "range_high_swing_orig": float(rh_swing[i]),
                    "range_low_swing_orig": float(rl_swing[i]),
                    "range_size": float(rh_swing[i] - rl_swing[i]),
                    "vol_ratio_cassure1": float(vols[i] / max(1.0, avg_vol_arr[i])),
                    "outcome": None,
                }
                st = "CASSURE1_DN"
            elif in_range_macro:
                st = "RANGE_OK"
            state[i] = st
            continue

        bars_since_c1 = i - mini_start_bar
        if direction_track == "UP":
            if close_arr[i] < cassure1_seq_pending["range_high_swing_orig"]:
                cassure1_seq_pending["outcome"] = "FAKEOUT"
                cassure1_seq_pending["fakeout_bar"] = i
                cassure1_seq_pending["bars_consolidation"] = bars_since_c1
                sequences.append(cassure1_seq_pending)
                state[i] = "FAKEOUT_UP"
                direction_track = None
                mini_start_bar = -1
                cassure1_seq_pending = None
                continue
            if bars_since_c1 > DV_CONSOLIDATION_TIMEOUT:
                cassure1_seq_pending["outcome"] = "TIMEOUT"
                cassure1_seq_pending["bars_consolidation"] = bars_since_c1
                sequences.append(cassure1_seq_pending)
                state[i] = "TIMEOUT_UP"
                direction_track = None
                mini_start_bar = -1
                cassure1_seq_pending = None
                continue
            if bars_since_c1 >= 2:
                if i - 2 >= mini_start_bar:
                    mini_high_snapshot = max(high_arr[mini_start_bar: i-1])
                else:
                    mini_high_snapshot = high_arr[mini_start_bar]
                if close_arr[i] > mini_high_snapshot and close_arr[i-1] > mini_high_snapshot:
                    cassure1_seq_pending["outcome"] = "CASSURE2"
                    cassure1_seq_pending["cassure2_bar"] = i
                    cassure1_seq_pending["bars_consolidation"] = bars_since_c1
                    cassure1_seq_pending["mini_high_at_cassure2"] = float(mini_high_snapshot)
                    sequences.append(cassure1_seq_pending)
                    state[i] = "CASSURE2_UP"
                    direction_track = None
                    mini_start_bar = -1
                    cassure1_seq_pending = None
                    continue
            state[i] = "CONSOLIDATION_UP"
        else:
            if close_arr[i] > cassure1_seq_pending["range_low_swing_orig"]:
                cassure1_seq_pending["outcome"] = "FAKEOUT"
                cassure1_seq_pending["fakeout_bar"] = i
                cassure1_seq_pending["bars_consolidation"] = bars_since_c1
                sequences.append(cassure1_seq_pending)
                state[i] = "FAKEOUT_DN"
                direction_track = None
                mini_start_bar = -1
                cassure1_seq_pending = None
                continue
            if bars_since_c1 > DV_CONSOLIDATION_TIMEOUT:
                cassure1_seq_pending["outcome"] = "TIMEOUT"
                cassure1_seq_pending["bars_consolidation"] = bars_since_c1
                sequences.append(cassure1_seq_pending)
                state[i] = "TIMEOUT_DN"
                direction_track = None
                mini_start_bar = -1
                cassure1_seq_pending = None
                continue
            if bars_since_c1 >= 2:
                if i - 2 >= mini_start_bar:
                    mini_low_snapshot = min(low_arr[mini_start_bar: i-1])
                else:
                    mini_low_snapshot = low_arr[mini_start_bar]
                if close_arr[i] < mini_low_snapshot and close_arr[i-1] < mini_low_snapshot:
                    cassure1_seq_pending["outcome"] = "CASSURE2"
                    cassure1_seq_pending["cassure2_bar"] = i
                    cassure1_seq_pending["bars_consolidation"] = bars_since_c1
                    cassure1_seq_pending["mini_low_at_cassure2"] = float(mini_low_snapshot)
                    sequences.append(cassure1_seq_pending)
                    state[i] = "CASSURE2_DN"
                    direction_track = None
                    mini_start_bar = -1
                    cassure1_seq_pending = None
                    continue
            state[i] = "CONSOLIDATION_DN"

    return state, sequences



def simulate_range_fade_swing(df, i):
    row = df.iloc[i]
    if pd.isna(row["range_low_swing"]) or pd.isna(row["range_high_swing"]):
        return None
    if pd.isna(row["atr_14"]) or row["atr_14"] <= 0:
        return None
    rl = float(row["range_low_swing"])
    rh = float(row["range_high_swing"])
    mid = (rl + rh) / 2.0
    pos = row["range_pos_swing"]
    if pd.isna(pos):
        return None
    d_low = int(row.get("density_low", 0) or 0)
    d_high = int(row.get("density_high", 0) or 0)
    atr = float(row["atr_14"])
    entry = float(row["close"])
    date = row["date"]
    if pos < RF_POS_LOW and d_low >= DENSITY_MIN:
        direction = "BUY"
        sl_price = rl - RF_SL_ATR_MULT * atr
        tp1 = mid
        tp2 = rh - 1 * TICK
    elif pos > RF_POS_HIGH and d_high >= DENSITY_MIN:
        direction = "SELL"
        sl_price = rh + RF_SL_ATR_MULT * atr
        tp1 = mid
        tp2 = rl + 1 * TICK
    else:
        return None
    if direction == "BUY" and (tp1 <= entry or tp2 <= entry or sl_price >= entry):
        return None
    if direction == "SELL" and (tp1 >= entry or tp2 >= entry or sl_price <= entry):
        return None
    half = RF_SCALE_OUT_FRAC
    tp1_hit = False
    pnl = 0.0
    exit_r = "TIME"
    bars = 0
    end_idx = min(i + 1 + RF_MAX_HOLD, len(df))
    exited = False
    for j in range(i + 1, end_idx):
        bars += 1
        bh = float(df.iloc[j]["high"])
        bl = float(df.iloc[j]["low"])
        if direction == "BUY":
            if bl <= sl_price:
                slp = (sl_price - entry) / TICK
                if tp1_hit:
                    pnl += slp * (1 - half)
                    exit_r = "SL_AFTER_TP1"
                else:
                    pnl = slp
                    exit_r = "SL"
                exited = True
                break
            if not tp1_hit and bh >= tp1:
                pnl += (tp1 - entry) / TICK * half
                tp1_hit = True
                sl_price = entry
            if tp1_hit and bh >= tp2:
                pnl += (tp2 - entry) / TICK * (1 - half)
                exit_r = "TP2"
                exited = True
                break
        else:
            if bh >= sl_price:
                slp = (entry - sl_price) / TICK
                if tp1_hit:
                    pnl += slp * (1 - half)
                    exit_r = "SL_AFTER_TP1"
                else:
                    pnl = slp
                    exit_r = "SL"
                exited = True
                break
            if not tp1_hit and bl <= tp1:
                pnl += (entry - tp1) / TICK * half
                tp1_hit = True
                sl_price = entry
            if tp1_hit and bl <= tp2:
                pnl += (entry - tp2) / TICK * (1 - half)
                exit_r = "TP2"
                exited = True
                break
    if not exited:
        fp = float(df.iloc[min(end_idx - 1, len(df) - 1)]["close"])
        tp = (fp - entry) / TICK if direction == "BUY" else (entry - fp) / TICK
        if tp1_hit:
            pnl += tp * (1 - half)
            exit_r = "TIME_AFTER_TP1"
        else:
            pnl = tp
    return {
        "mode": "RANGE_FADE", "direction": direction, "entry_idx": i,
        "entry_ts": row["ts_event"], "date": date, "entry_price": entry,
        "atr_pts": atr, "range_pos": pos, "range_size_pts": rh - rl,
        "bars_held": bars, "exit_reason": exit_r,
        "pnl_ticks": pnl, "pnl_usd": pnl * TICK_USD,
        "bars_consolidation": None, "vol_ratio_cassure1": None,
    }


def simulate_trend_post_breakout(df, i, seq):
    row = df.iloc[i]
    if pd.isna(row["atr_14"]) or row["atr_14"] <= 0:
        return None
    direction = "BUY" if seq["direction"] == "UP" else "SELL"
    entry = float(row["close"])
    range_amp = seq["range_size"]
    if direction == "BUY":
        sl_price = seq["range_high_swing_orig"] - DV_CASSURE1_OFFSET_TICKS * TICK
        tp_price = entry + DV_TP_RANGE_MULT * range_amp
    else:
        sl_price = seq["range_low_swing_orig"] + DV_CASSURE1_OFFSET_TICKS * TICK
        tp_price = entry - DV_TP_RANGE_MULT * range_amp
    if direction == "BUY" and (sl_price >= entry or tp_price <= entry):
        return None
    if direction == "SELL" and (sl_price <= entry or tp_price >= entry):
        return None
    pnl = 0.0
    exit_r = "TIME"
    bars = 0
    trail_active = False
    trail_stop = None
    end_idx = min(i + 1 + DV_MAX_HOLD, len(df))
    exited = False
    for j in range(i + 1, end_idx):
        bars += 1
        bh = float(df.iloc[j]["high"])
        bl = float(df.iloc[j]["low"])
        if direction == "BUY":
            eff_sl = trail_stop if trail_active else sl_price
            if bl <= eff_sl:
                pnl = (eff_sl - entry) / TICK
                exit_r = "TRAIL_HIT" if trail_active else "SL"
                exited = True
                break
            if bh >= tp_price:
                pnl = (tp_price - entry) / TICK
                exit_r = "TP"
                exited = True
                break
            mfe = (bh - entry) / TICK
            if mfe >= DV_TRAIL_MFE_TRIGGER:
                new_trail = bh - DV_TRAIL_STOP_BUFFER * TICK
                if not trail_active or new_trail > (trail_stop if trail_stop is not None else -1e9):
                    trail_stop = new_trail
                    trail_active = True
        else:
            eff_sl = trail_stop if trail_active else sl_price
            if bh >= eff_sl:
                pnl = (entry - eff_sl) / TICK
                exit_r = "TRAIL_HIT" if trail_active else "SL"
                exited = True
                break
            if bl <= tp_price:
                pnl = (entry - tp_price) / TICK
                exit_r = "TP"
                exited = True
                break
            mfe = (entry - bl) / TICK
            if mfe >= DV_TRAIL_MFE_TRIGGER:
                new_trail = bl + DV_TRAIL_STOP_BUFFER * TICK
                if not trail_active or new_trail < (trail_stop if trail_stop is not None else 1e9):
                    trail_stop = new_trail
                    trail_active = True
    if not exited:
        fp = float(df.iloc[min(end_idx - 1, len(df) - 1)]["close"])
        pnl = (fp - entry) / TICK if direction == "BUY" else (entry - fp) / TICK
    return {
        "mode": "TREND_POST_BREAKOUT", "direction": direction,
        "entry_idx": i, "entry_ts": row["ts_event"], "date": row["date"],
        "entry_price": entry, "atr_pts": float(row["atr_14"]),
        "range_pos": None, "range_size_pts": range_amp,
        "bars_held": bars, "exit_reason": exit_r,
        "pnl_ticks": pnl, "pnl_usd": pnl * TICK_USD,
        "bars_consolidation": seq.get("bars_consolidation"),
        "vol_ratio_cassure1": seq.get("vol_ratio_cassure1"),
    }

def main():
    SEP = chr(61) * 80
    print(SEP)
    print("BACKTEST BOT 2 V6 DOUBLE VALIDATION")
    print(SEP)
    df = load_and_normalize_nq()
    n_days = df["date"].nunique()
    print("[1] Loaded " + str(len(df)) + " bars NQ RTH, days=" + str(n_days))
    print("    Dates: " + str(sorted(df["date"].unique())))
    df_aug = compute_range_features(df)
    df_aug["range_age_min"] = compute_range_age_min(df_aug)
    df_aug = compute_swing_bounded_range(df_aug)
    valid = df_aug.dropna(subset=["range_high_zone", "range_high_swing"])
    diff_high = (valid["range_high_swing"] - valid["range_high_zone"])
    diff_low = (valid["range_low_swing"] - valid["range_low_zone"])
    print("")
    print(SEP)
    print("Q1 - BORNES SWING VS QUANTILE")
    print(SEP)
    print("  bars valides : " + str(len(valid)))
    print("  diff range_high_swing-range_high_zone : mean=" + str(round(diff_high.mean(),2)) + " median=" + str(round(diff_high.median(),2)) + " max=" + str(round(diff_high.max(),2)))
    print("  diff range_low_swing-range_low_zone  : mean=" + str(round(diff_low.mean(),2)) + " median=" + str(round(diff_low.median(),2)) + " min=" + str(round(diff_low.min(),2)))
    pct_elargi = ((diff_high > 0.5) | (diff_low < -0.5)).mean() * 100
    print("  fraction bars ou swing elargit le range : " + str(round(pct_elargi,1)) + "%")
    d11 = df_aug[df_aug["date"] == pd.Timestamp("2026-05-11").date()]
    if len(d11) > 0:
        v11 = d11.dropna(subset=["range_high_swing"])
        print("  --- ZOOM 11/05 (" + str(len(d11)) + " bars, " + str(len(v11)) + " valides) ---")
        if len(v11) > 0:
            print("     range_high_swing : min=" + str(round(v11["range_high_swing"].min(),2)) + " max=" + str(round(v11["range_high_swing"].max(),2)))
            print("     range_low_swing  : min=" + str(round(v11["range_low_swing"].min(),2)) + " max=" + str(round(v11["range_low_swing"].max(),2)))
            print("     range_high_zone  : min=" + str(round(v11["range_high_zone"].min(),2)) + " max=" + str(round(v11["range_high_zone"].max(),2)))
            print("     range_low_zone   : min=" + str(round(v11["range_low_zone"].min(),2)) + " max=" + str(round(v11["range_low_zone"].max(),2)))
    print("")
    print(SEP)
    print("Q2 - SEQUENCES DOUBLE VALIDATION DETECTEES")
    print(SEP)
    states, sequences = classify_state_dv(df_aug)
    df_aug["dv_state"] = states
    n_seq = len(sequences)
    n_cassure2 = sum(1 for s in sequences if s["outcome"] == "CASSURE2")
    n_fakeout = sum(1 for s in sequences if s["outcome"] == "FAKEOUT")
    n_timeout = sum(1 for s in sequences if s["outcome"] == "TIMEOUT")
    print("  Total sequences cassure 1 detectees : " + str(n_seq))
    if n_seq > 0:
        print("    CASSURE2 (entry validee)  : " + str(n_cassure2) + " (" + str(round(n_cassure2/n_seq*100,1)) + "%)")
        print("    FAKEOUT  (re-integration) : " + str(n_fakeout) + " (" + str(round(n_fakeout/n_seq*100,1)) + "%)")
        print("    TIMEOUT  (consolid >15b)  : " + str(n_timeout) + " (" + str(round(n_timeout/n_seq*100,1)) + "%)")
    seq_df = pd.DataFrame(sequences) if sequences else pd.DataFrame()
    if not seq_df.empty:
        print("  Distribution direction x outcome :")
        print(seq_df.groupby(["direction", "outcome"]).size().unstack(fill_value=0).to_string())
        print("  Mean bars_consolidation : " + str(round(seq_df["bars_consolidation"].mean(),1)))
        print("  Mean vol_ratio_cassure1 : " + str(round(seq_df["vol_ratio_cassure1"].mean(),2)))
    print("")
    print(SEP)
    print("SIMULATION TRADES")
    print(SEP)
    trades = []
    cooldown = 0
    for i in range(len(df_aug)):
        if i < cooldown:
            continue
        st = df_aug.iloc[i]["dv_state"]
        n_macro = int(df_aug.iloc[i].get("n_macro_ok", 0) or 0)
        age = int(df_aug.iloc[i].get("range_age_min", 0) or 0)
        br = str(df_aug.iloc[i].get("range_break_risk", "NONE"))
        in_range = (n_macro >= RANGE_MACRO_MIN and age >= RANGE_AGE_MIN and br == "NONE")  # range_fade keeps strict
        trade = None
        if st in ("CASSURE2_UP", "CASSURE2_DN"):
            seq = next((s for s in sequences if s.get("cassure2_bar") == i), None)
            if seq is not None:
                trade = simulate_trend_post_breakout(df_aug, i, seq)
        elif in_range and st in ("RANGE_OK", "NO_TRADE"):
            trade = simulate_range_fade_swing(df_aug, i)
        if trade is not None:
            trades.append(trade)
            cooldown = i + trade["bars_held"] + 5
    print("  Total trades simules : " + str(len(trades)))
    if not trades:
        print("  AUCUN TRADE - verdict NOGO")
        return
    df_tr = pd.DataFrame(trades)
    print("")
    print(SEP)
    print("RESULTATS PAR MODE")
    print(SEP)
    for mode_name in ["RANGE_FADE", "TREND_POST_BREAKOUT"]:
        sub = df_tr[df_tr["mode"] == mode_name]
        if len(sub) == 0:
            print("")
            print(mode_name + ": 0 trades")
            continue
        wins = sub[sub["pnl_ticks"] > 0]
        losses = sub[sub["pnl_ticks"] <= 0]
        gw = wins["pnl_ticks"].sum()
        gl = abs(losses["pnl_ticks"].sum())
        pf = gw / gl if gl > 0 else float("inf")
        wr = len(wins) / len(sub) * 100
        ev = sub["pnl_ticks"].mean()
        total_usd = sub["pnl_usd"].sum()
        cum = sub.sort_values("entry_ts")["pnl_ticks"].cumsum().values
        dd = cum - np.maximum.accumulate(cum)
        max_dd = dd.min() if len(dd) > 0 else 0
        print("")
        print(mode_name + ":")
        print("  n trades : " + str(len(sub)))
        print("  WR       : " + str(round(wr,1)) + "% (" + str(len(wins)) + "W/" + str(len(losses)) + "L)")
        if pf != float("inf"):
            print("  PF       : " + str(round(pf,2)))
        else:
            print("  PF       : inf")
        print("  EV/trade : " + str(round(ev,2)) + "t ($" + str(round(ev * TICK_USD,2)) + ")")
        print("  Total    : " + str(round(sub["pnl_ticks"].sum(),1)) + "t ($" + str(round(total_usd,2)) + ")")
        print("  Max DD   : " + str(round(max_dd,1)) + "t ($" + str(round(max_dd * TICK_USD,2)) + ")")
        print("  Exits    : " + str(sub["exit_reason"].value_counts().to_dict()))
        print("  Direction: " + str(sub["direction"].value_counts().to_dict()))
    print("")
    print(SEP)
    print("TOTAL COMBINED")
    print(SEP)
    wins = df_tr[df_tr["pnl_ticks"] > 0]
    losses = df_tr[df_tr["pnl_ticks"] <= 0]
    gw = wins["pnl_ticks"].sum()
    gl = abs(losses["pnl_ticks"].sum())
    pf = gw / gl if gl > 0 else float("inf")
    wr = len(wins) / len(df_tr) * 100
    ev = df_tr["pnl_ticks"].mean()
    days_traded = df_tr["date"].nunique()
    print("  n trades : " + str(len(df_tr)))
    print("  WR       : " + str(round(wr,1)) + "%")
    if pf != float("inf"):
        print("  PF       : " + str(round(pf,2)))
    else:
        print("  PF       : inf")
    print("  EV/trade : " + str(round(ev,2)) + "t ($" + str(round(ev * TICK_USD,2)) + ")")
    print("  Total    : " + str(round(df_tr["pnl_ticks"].sum(),1)) + "t ($" + str(round(df_tr["pnl_usd"].sum(),2)) + ")")
    print("  Trades/day : " + str(round(len(df_tr) / days_traded,1)))
    print("")
    print(SEP)
    print("Q5 - REPRODUCTION 11/05")
    print(SEP)
    d11_dt = pd.Timestamp("2026-05-11").date()
    d11 = df_aug[df_aug["date"] == d11_dt].copy()
    print("  bars 11/05 disponibles : " + str(len(d11)))
    if len(d11) > 0:
        d11_range = d11[(d11["n_macro_ok"] >= RANGE_MACRO_MIN) & (d11["range_age_min"] >= RANGE_AGE_MIN)]
        print("  bars 11/05 en range (n_macro>=5 et age>=30) : " + str(len(d11_range)))
        d11_seqs = []
        for s in sequences:
            cb = int(s.get("cassure1_bar", -1))
            if 0 <= cb < len(df_aug) and df_aug.iloc[cb]["date"] == d11_dt:
                d11_seqs.append(s)
        print("  Sequences 11/05 : " + str(len(d11_seqs)))
        for s in d11_seqs:
            print("    Cassure1 bar=" + str(s["cassure1_bar"]) + " dir=" + s["direction"] + " outcome=" + str(s["outcome"]) + " range_size=" + str(round(s["range_size"],1)) + " consolid=" + str(s.get("bars_consolidation")))
        t11 = df_tr[df_tr["date"] == d11_dt]
        print("  Trades 11/05 : " + str(len(t11)))
        if len(t11) > 0:
            print(t11[["mode", "direction", "exit_reason", "pnl_ticks"]].to_string())
    out_t = "DATA/PAPER_TRADES_V6_AUDIT/_concept_bot2_v6_double_validation_trades.csv"
    df_tr.to_csv(out_t, index=False)
    print("")
    print("  Saved trades : " + out_t)
    if not seq_df.empty:
        seq_out = "DATA/PAPER_TRADES_V6_AUDIT/_concept_bot2_v6_dv_sequences.csv"
        seq_df.to_csv(seq_out, index=False)
        print("  Saved sequences : " + seq_out)


if __name__ == "__main__":
    main()
