"""Backtester Bot 4 — Range Fade Confluence Multi-Source.

Spec : DOCS/BOT4_RANGE_FADE_CONFLUENCE_DESIGN.md
- Charge V4 enriched NQ/ES + MenthorQ JSON daily
- Detecte zones confluence (>=2 niveaux dans 5 ticks)
- Confirme via bar suivante (close-beyond + footprint + delta)
- Backteste 5 variantes V11.0 -> V11.4 (filtres additifs)
- Walk-forward 12-fold + DSR Lopez
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

try:
    from scipy import stats as scstats
except ImportError:
    scstats = None

# ---------------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------------
ROOT = Path(r"D:\TRADING_SIERRA_CHART_AUTO")
PARQUET_BASE = ROOT / "DATA" / "datasets" / "v4_enriched"
MENTHORQ_DIR = ROOT / "DATA" / "MENTHORQ"
OUT_DIR = ROOT / "LOGS" / "bot4_research"

TICK_BY_SYMBOL = {"NQ": 0.25, "ES": 0.25}
TICK_VALUE_USD_BY_SYMBOL = {"NQ": 0.50, "ES": 1.25}  # MNQ/MES micro

BUFFER_ZONE_PCT = 0.05            # 0.05% touch
CONFLUENCE_MIN = 2
BUFFER_CONFLUENCE_TICKS = 5       # ~1.25 pts NQ/ES
TARGET_R = 1.5
SL_BUFFER_TICKS = 5
COOLDOWN_BARS = 30
MAX_PER_ZONE_PER_DAY = 2
TIMEOUT_BARS = 120

SLIPPAGE_TICKS = 1
COMMISSION_USD = 0.50             # par RT par micro

MAX_CARRYFORWARD_DAYS = 5

PERIOD_START = "2025-12-15"
PERIOD_END = "2026-05-24"

VARIANTS = ["V11.0", "V11.1", "V11.2", "V11.3", "V11.4"]
WF_FOLDS = 12

LOG_PREFIX_TOUCH = "BOT4_RESEARCH_TOUCH_DETECTED"
LOG_PREFIX_ENTRY = "BOT4_RESEARCH_ENTRY_EMITTED"
LOG_PREFIX_CLOSE = "BOT4_RESEARCH_TRADE_CLOSED"


# ---------------------------------------------------------------------
# DATACLASSES
# ---------------------------------------------------------------------
@dataclass(frozen=True)
class LevelSource:
    name: str
    category: str
    price: float


@dataclass
class ConfluenceZone:
    side: str                   # SHORT (zone resistance) ou LONG (zone support)
    levels: list                # list[LevelSource]
    zone_min: float
    zone_max: float
    touch_bar_idx: int = -1     # bar ou zone touchee (armee pour confirmation)
    last_emission_bar: int = -1
    emissions_today: int = 0


@dataclass(frozen=True)
class EntryDecision:
    side: str
    n_levels: int
    level_categories: tuple
    level_names: tuple
    entry_price: float
    sl_price: float
    tp_price: float
    sl_ticks: int
    tp_ticks: int
    tp_mode: str                # "VPOC" ou "RANGE_OPPOSITE"
    bar_idx: int
    bar_ts: pd.Timestamp
    variant: str


@dataclass
class OpenPosition:
    decision: EntryDecision
    opened_bar_idx: int


@dataclass
class TradeResult:
    variant: str
    symbol: str
    side: str
    entry_bar_idx: int
    exit_bar_idx: int
    entry_ts: pd.Timestamp
    exit_ts: pd.Timestamp
    entry_price: float
    exit_price: float
    sl_price: float
    tp_price: float
    sl_ticks: int
    tp_ticks: int
    n_levels: int
    level_categories: str
    level_names: str
    tp_mode: str
    exit_reason: str            # TP / SL / TIMEOUT
    pnl_ticks: float
    pnl_usd: float
    duration_bars: int


# ---------------------------------------------------------------------
# MENTHORQ LOADER
# ---------------------------------------------------------------------
def _safe_float(v):
    if v is None:
        return None
    try:
        f = float(v)
        if math.isnan(f) or f <= 0:
            return None
        return f
    except (TypeError, ValueError):
        return None


def _extract_top_gex(gex_data) -> list:
    """Extract top GEX strikes prices from netgex.resource.data.
    Structure observee : data["Top Net GEX Strikes"] = list[float] (3 strikes).
    """
    if not isinstance(gex_data, dict):
        return []
    raw = gex_data.get("Top Net GEX Strikes", [])
    if not isinstance(raw, list):
        return []
    out = []
    for v in raw:
        f = _safe_float(v)
        if f is not None:
            out.append(f)
    return out


def _extract_bl_levels(bl_data) -> list:
    """BL levels souvent vides. Si liste populated, extraire prix."""
    if not isinstance(bl_data, (list, dict)):
        return []
    out = []
    if isinstance(bl_data, list):
        for item in bl_data:
            if isinstance(item, (int, float)):
                f = _safe_float(item)
                if f is not None:
                    out.append(f)
            elif isinstance(item, dict):
                # tenter cles communes
                for cand in ("price", "level", "value"):
                    f = _safe_float(item.get(cand))
                    if f is not None:
                        out.append(f)
                        break
    elif isinstance(bl_data, dict):
        for v in bl_data.values():
            f = _safe_float(v)
            if f is not None:
                out.append(f)
    return out[:10]


def load_menthorq_cache(menthorq_dir: Path) -> dict:
    """Cache {date_str(YYYY-MM-DD) : {"NQ": {...}, "ES": {...}}}.

    Cles canoniques internes : Call Resistance, Put Support, High Vol Level,
    Call Resistance 0DTE, Put Support 0DTE, 1D Max, 1D Min,
    bl_levels (list), top_gex_strikes (list).
    """
    cache = {}
    for fp in sorted(menthorq_dir.glob("*_menthorq_complete.json")):
        stem = fp.stem.split("_")[0]
        if len(stem) != 8 or not stem.isdigit():
            continue
        date_iso = f"{stem[:4]}-{stem[4:6]}-{stem[6:8]}"
        try:
            j = json.load(open(fp, encoding="utf-8"))
        except Exception:
            continue
        for sym in ("NQ", "ES"):
            sec = j.get(sym, {}).get("structured", {})
            kl = sec.get("key_levels", {}).get("resource", {}).get("data", {})
            bl = sec.get("bl_levels", {}).get("resource", {}).get("data", None)
            gex = sec.get("netgex", {}).get("resource", {}).get("data", {})
            if not isinstance(kl, dict):
                continue
            entry = {
                "Call Resistance": _safe_float(kl.get("Call Resistance")),
                "Put Support": _safe_float(kl.get("Put Support")),
                "High Vol Level": _safe_float(kl.get("High Vol Level")),
                "Call Resistance 0DTE": _safe_float(kl.get("Call Resistance 0DTE")),
                "Put Support 0DTE": _safe_float(kl.get("Put Support 0DTE")),
                "1D Max": _safe_float(kl.get("1D Max.")),
                "1D Min": _safe_float(kl.get("1D Min.")),
                "bl_levels": _extract_bl_levels(bl),
                "top_gex_strikes": _extract_top_gex(gex),
            }
            cache.setdefault(date_iso, {})[sym] = entry
    return cache


def lookup_mq_for_date(cache: dict, date_iso: str, symbol: str) -> Optional[dict]:
    """Lookup MQ data avec carry-forward jusqu'a MAX_CARRYFORWARD_DAYS."""
    if not cache:
        return None
    d = datetime.fromisoformat(date_iso)
    for offset in range(MAX_CARRYFORWARD_DAYS + 1):
        cand = (d - timedelta(days=offset)).strftime("%Y-%m-%d")
        if cand in cache and symbol in cache[cand]:
            return cache[cand][symbol]
    return None


# ---------------------------------------------------------------------
# PARQUET LOADER
# ---------------------------------------------------------------------
def load_parquet_period(symbol: str, start: str, end: str) -> pd.DataFrame:
    sym_key = f"symbol={symbol}.c.0"
    base = PARQUET_BASE / sym_key
    if not base.exists():
        return pd.DataFrame()
    parts = []
    cur = datetime.fromisoformat(start).replace(day=1)
    end_dt = datetime.fromisoformat(end)
    while cur <= end_dt:
        fp = base / f"year={cur.year}" / f"month={cur.month:02d}" / "data.parquet"
        if fp.exists():
            parts.append(pd.read_parquet(fp))
        # next month
        if cur.month == 12:
            cur = cur.replace(year=cur.year + 1, month=1)
        else:
            cur = cur.replace(month=cur.month + 1)
    if not parts:
        return pd.DataFrame()
    df = pd.concat(parts, ignore_index=True)
    df = df.sort_values("ts_event").reset_index(drop=True)
    # tz handling
    if pd.api.types.is_datetime64_any_dtype(df["ts_event"]):
        if df["ts_event"].dt.tz is None:
            df["ts_event"] = df["ts_event"].dt.tz_localize("UTC")
        else:
            df["ts_event"] = df["ts_event"].dt.tz_convert("UTC")
    start_ts = pd.Timestamp(start, tz="UTC")
    end_ts = pd.Timestamp(end, tz="UTC") + pd.Timedelta(days=1)
    df = df[(df["ts_event"] >= start_ts) & (df["ts_event"] < end_ts)].reset_index(drop=True)
    df["date_iso"] = df["ts_event"].dt.strftime("%Y-%m-%d")
    return df


# ---------------------------------------------------------------------
# LEVEL EXTRACTION
# ---------------------------------------------------------------------
_PARQUET_LEVEL_MAP = [
    # (name, category, column)
    ("CUR_VAH", "MP", "cur_vah"),
    ("CUR_VAL", "MP", "cur_val"),
    ("CUR_VPOC", "MP", "cur_vpoc"),
    ("PREV_VAH", "MP", "prev_vah"),
    ("PREV_VAL", "MP", "prev_val"),
    ("PREV_VPOC", "MP", "prev_vpoc"),
    ("VWAP_D", "VWAP", "vwap_d"),
    ("VWAP_SD1U", "VWAP", "vwap_d_sd1u"),
    ("VWAP_SD1D", "VWAP", "vwap_d_sd1d"),
    ("VWAP_SD2U", "VWAP", "vwap_d_sd2u"),
    ("VWAP_SD2D", "VWAP", "vwap_d_sd2d"),
    ("VWAP_SD3U", "VWAP", "vwap_d_sd3u"),
    ("VWAP_SD3D", "VWAP", "vwap_d_sd3d"),
    ("VWAP_W_SD1U", "VWAP_W", "vwap_w_sd1u"),
    ("VWAP_W_SD1D", "VWAP_W", "vwap_w_sd1d"),
    ("VWAP_W_SD2U", "VWAP_W", "vwap_w_sd2u"),
    ("VWAP_W_SD2D", "VWAP_W", "vwap_w_sd2d"),
    ("VWAP_W_SD3U", "VWAP_W", "vwap_w_sd3u"),
    ("VWAP_W_SD3D", "VWAP_W", "vwap_w_sd3d"),
    ("VWAP_M_SD1U", "VWAP_M", "vwap_m_sd1u"),
    ("VWAP_M_SD1D", "VWAP_M", "vwap_m_sd1d"),
    ("VWAP_M_SD2U", "VWAP_M", "vwap_m_sd2u"),
    ("VWAP_M_SD2D", "VWAP_M", "vwap_m_sd2d"),
    ("VWAP_M_SD3U", "VWAP_M", "vwap_m_sd3u"),
    ("VWAP_M_SD3D", "VWAP_M", "vwap_m_sd3d"),
    ("SWING_HIGH", "SWING", "_last_swing_high_price"),
    ("SWING_LOW", "SWING", "_last_swing_low_price"),
    ("IB_HIGH", "IB", "ib_high"),
    ("IB_LOW", "IB", "ib_low"),
    ("OVN_HIGH", "OVN", "ovn_high"),
    ("OVN_LOW", "OVN", "ovn_low"),
    ("ASIA_HIGH", "ASIA", "asia_high"),
    ("ASIA_LOW", "ASIA", "asia_low"),
    ("ASIA_OPEN", "ASIA", "asia_open"),
    ("LONDON_HIGH", "LONDON", "london_high"),
    ("LONDON_LOW", "LONDON", "london_low"),
    ("LONDON_OPEN", "LONDON", "london_open"),
]

_OF_DIST_COLS = [
    ("BIG_ASK_NEAREST", "OF", "dist_big_ask_nearest_pct"),
    ("BIG_BID_NEAREST", "OF", "dist_big_bid_nearest_pct"),
    ("CLUSTER_NEAREST_DN", "OF", "dist_cluster_nearest_dn_pct"),
    ("CLUSTER_NEAREST_UP", "OF", "dist_cluster_nearest_up_pct"),
]

_MQ_KEY_LEVELS = [
    ("MQ_CALL_RES", "MENTHORQ", "Call Resistance"),
    ("MQ_PUT_SUP", "MENTHORQ", "Put Support"),
    ("MQ_HVL", "MENTHORQ", "High Vol Level"),
    ("MQ_CALL_0DTE", "MENTHORQ", "Call Resistance 0DTE"),
    ("MQ_PUT_0DTE", "MENTHORQ", "Put Support 0DTE"),
    ("MQ_1D_MAX", "MENTHORQ", "1D Max"),
    ("MQ_1D_MIN", "MENTHORQ", "1D Min"),
]


def extract_levels_for_bar(row, mq_today: Optional[dict]) -> list:
    """Retourne list[LevelSource] (~37-50)."""
    close = row.get("close")
    if close is None or pd.isna(close) or close <= 0:
        return []
    levels = []
    for name, cat, col in _PARQUET_LEVEL_MAP:
        v = row.get(col)
        if v is not None and not pd.isna(v) and v > 0:
            levels.append(LevelSource(name=name, category=cat, price=float(v)))
    for name, cat, col in _OF_DIST_COLS:
        d = row.get(col)
        if d is not None and not pd.isna(d):
            price = float(close) * (1.0 + float(d) / 100.0)
            if price > 0:
                levels.append(LevelSource(name=name, category=cat, price=price))
    if mq_today:
        for name, cat, key in _MQ_KEY_LEVELS:
            p = mq_today.get(key)
            if p is not None and p > 0:
                levels.append(LevelSource(name=name, category=cat, price=float(p)))
        for i, p in enumerate(mq_today.get("bl_levels") or []):
            levels.append(LevelSource(name=f"MQ_BL_{i + 1}", category="MQ_BL", price=float(p)))
        for i, p in enumerate(mq_today.get("top_gex_strikes") or []):
            levels.append(LevelSource(name=f"MQ_GEX_{i + 1}", category="MQ_GEX", price=float(p)))
    return levels


# ---------------------------------------------------------------------
# CONFLUENCE DETECTION
# ---------------------------------------------------------------------
def detect_confluence_zones(levels: list, buffer_ticks: int, tick_size: float, close_px: float) -> list:
    """Retourne list[(zone_min, zone_max, [LevelSource], side)].

    side : SHORT si zone au-dessus du close (resistance), LONG si en-dessous.
    Algorithme : tri par prix, fenetre glissante ; un niveau peut entrer dans
    plusieurs zones potentielles, on garde la zone MAXIMALE non-chevauchante
    (greedy left-to-right).
    """
    if len(levels) < CONFLUENCE_MIN:
        return []
    buffer_pts = buffer_ticks * tick_size
    sorted_lvl = sorted(levels, key=lambda l: l.price)
    zones = []
    i = 0
    n = len(sorted_lvl)
    while i < n:
        j = i + 1
        while j < n and sorted_lvl[j].price - sorted_lvl[i].price <= buffer_pts:
            j += 1
        if j - i >= CONFLUENCE_MIN:
            zlist = sorted_lvl[i:j]
            zone_min = zlist[0].price
            zone_max = zlist[-1].price
            mid = (zone_min + zone_max) * 0.5
            side = "SHORT" if mid >= close_px else "LONG"
            zones.append((zone_min, zone_max, zlist, side))
            i = j
        else:
            i += 1
    return zones


def _zone_id(zone_min: float, zone_max: float) -> str:
    return f"{zone_min:.2f}_{zone_max:.2f}"


# ---------------------------------------------------------------------
# CONFIRMATION FILTERS (variantes V11.0 -> V11.4)
# ---------------------------------------------------------------------
def check_confirmation(row, side: str, zone_min: float, zone_max: float,
                       variant: str) -> bool:
    """Verifie filtres de confirmation pour cette bar (t+1 par rapport touch)."""
    close = row.get("close")
    if close is None or pd.isna(close):
        return False
    # (1) confluence touch deja verifie en amont
    # (2) close-beyond
    if side == "SHORT":
        if close >= zone_min:                      # pas casse en-dessous resistance
            return False
    else:  # LONG
        if close <= zone_max:                      # pas casse au-dessus support
            return False
    if variant == "V11.0":
        return True
    # (3) footprint
    if side == "SHORT":
        long_bar = row.get("long_dn_bar") or 0
        n_cluster = row.get("n_long_dn_cluster_within_0_2pct") or 0
    else:
        long_bar = row.get("long_up_bar") or 0
        n_cluster = row.get("n_long_up_cluster_within_0_2pct") or 0
    if not (long_bar == 1 or n_cluster >= 2):
        return False
    if variant == "V11.1":
        return True
    # (4) delta_bar oppose
    delta = row.get("delta_bar")
    if delta is None or pd.isna(delta):
        return False
    if side == "SHORT" and delta >= 0:
        return False
    if side == "LONG" and delta <= 0:
        return False
    if variant == "V11.2":
        return True
    # (5) range session >= 1.5 ATR
    sess_range_atr = row.get("sess_range_atr")
    if sess_range_atr is None or pd.isna(sess_range_atr) or sess_range_atr < 1.5:
        return False
    if variant == "V11.3":
        return True
    # (6) vwap_slope_10 du bon cote
    slope = row.get("vwap_slope_10")
    if slope is None or pd.isna(slope):
        return False
    if side == "SHORT" and slope >= 0:
        return False
    if side == "LONG" and slope <= 0:
        return False
    return True


# ---------------------------------------------------------------------
# TP / SL CALCULATION
# ---------------------------------------------------------------------
def compute_sl_tp(row, side: str, zone_min: float, zone_max: float,
                  entry_price: float, tick_size: float) -> tuple:
    """Retourne (sl, tp, tp_mode, sl_ticks, tp_ticks)."""
    sl_buffer = SL_BUFFER_TICKS * tick_size
    if side == "SHORT":
        sl = zone_max + sl_buffer
    else:
        sl = zone_min - sl_buffer
    sl_ticks = int(round(abs(sl - entry_price) / tick_size))
    # TP magnet sur cur_vpoc si valide
    cur_vpoc = row.get("cur_vpoc")
    tp_mode = "RANGE_OPPOSITE"
    tp_price = None
    if cur_vpoc is not None and not pd.isna(cur_vpoc) and cur_vpoc > 0:
        if side == "SHORT" and cur_vpoc < entry_price:
            if (entry_price - cur_vpoc) / tick_size >= 5:
                tp_price = float(cur_vpoc)
                tp_mode = "VPOC"
        elif side == "LONG" and cur_vpoc > entry_price:
            if (cur_vpoc - entry_price) / tick_size >= 5:
                tp_price = float(cur_vpoc)
                tp_mode = "VPOC"
    if tp_price is None:
        # fallback : autre extreme range = R-target multiple
        if side == "SHORT":
            tp_price = entry_price - (sl_ticks * tick_size * TARGET_R)
        else:
            tp_price = entry_price + (sl_ticks * tick_size * TARGET_R)
    tp_ticks = int(round(abs(tp_price - entry_price) / tick_size))
    return sl, tp_price, tp_mode, sl_ticks, tp_ticks


# ---------------------------------------------------------------------
# BACKTEST CORE
# ---------------------------------------------------------------------
def _bar_exit_check(open_pos: OpenPosition, row, tick_size: float) -> Optional[tuple]:
    """Retourne (exit_price, exit_reason) ou None."""
    d = open_pos.decision
    high = row.get("high")
    low = row.get("low")
    if pd.isna(high) or pd.isna(low):
        return None
    if d.side == "SHORT":
        # SL hit si high >= sl (intraday wick)
        if high >= d.sl_price:
            return (d.sl_price, "SL")
        if low <= d.tp_price:
            return (d.tp_price, "TP")
    else:
        if low <= d.sl_price:
            return (d.sl_price, "SL")
        if high >= d.tp_price:
            return (d.tp_price, "TP")
    return None


def run_backtest(df: pd.DataFrame, symbol: str, mq_cache: dict,
                 variant: str, verbose: bool = False) -> tuple:
    """Run backtest pour 1 symbol + 1 variant.

    Retourne (list[TradeResult], stats dict).
    """
    tick = TICK_BY_SYMBOL[symbol]
    tick_val_usd = TICK_VALUE_USD_BY_SYMBOL[symbol]
    n_rows = len(df)
    if n_rows < 50:
        return [], {"n_bars": n_rows, "n_zones_touched": 0, "n_entries": 0, "n_closes": 0}

    trades = []
    open_pos: Optional[OpenPosition] = None
    last_emission_bar_global = -10_000
    daily_emission_counts: dict = {}        # (date_iso, zone_id) -> count
    # zones armes apres touch (key = zone_id), valeur = dict {bar_touch, side, zone_min, zone_max, levels}
    armed_zones: dict = {}

    stats = {
        "n_bars": n_rows,
        "n_zones_detected_total": 0,
        "n_zones_touched": 0,
        "n_confirm_pass": 0,
        "n_entries": 0,
        "n_closes": 0,
        "n_pos_skipped_cooldown": 0,
        "n_pos_skipped_open": 0,
        "n_pos_skipped_dailycap": 0,
        "level_counts": [],
    }

    # Pre-extract mq_today par date pour eviter lookup repete
    mq_by_date: dict = {}
    for d_iso in df["date_iso"].unique():
        mq_by_date[d_iso] = lookup_mq_for_date(mq_cache, d_iso, symbol)

    # Iter par rows via itertuples pour vitesse
    rows = df.to_dict(orient="records")

    for idx, row in enumerate(rows):
        # Exit logic if pos open
        if open_pos is not None:
            res = _bar_exit_check(open_pos, row, tick)
            timeout = (idx - open_pos.opened_bar_idx) >= TIMEOUT_BARS
            if res is not None:
                exit_price, exit_reason = res
            elif timeout:
                exit_price = float(row.get("close"))
                exit_reason = "TIMEOUT"
            else:
                exit_price = None
                exit_reason = None
            if exit_price is not None:
                d = open_pos.decision
                # Cost : slippage 1 tick au pire + commission RT
                if d.side == "SHORT":
                    raw_ticks = (d.entry_price - exit_price) / tick
                else:
                    raw_ticks = (exit_price - d.entry_price) / tick
                slip_ticks = SLIPPAGE_TICKS  # cost 1 tick par side (entry + exit) -> conservative
                pnl_ticks = raw_ticks - 2 * slip_ticks
                pnl_usd = pnl_ticks * tick_val_usd - 2 * COMMISSION_USD
                trades.append(TradeResult(
                    variant=variant,
                    symbol=symbol,
                    side=d.side,
                    entry_bar_idx=open_pos.opened_bar_idx,
                    exit_bar_idx=idx,
                    entry_ts=df.iloc[open_pos.opened_bar_idx]["ts_event"],
                    exit_ts=row["ts_event"],
                    entry_price=d.entry_price,
                    exit_price=float(exit_price),
                    sl_price=d.sl_price,
                    tp_price=d.tp_price,
                    sl_ticks=d.sl_ticks,
                    tp_ticks=d.tp_ticks,
                    n_levels=d.n_levels,
                    level_categories=",".join(d.level_categories),
                    level_names=",".join(d.level_names),
                    tp_mode=d.tp_mode,
                    exit_reason=exit_reason,
                    pnl_ticks=pnl_ticks,
                    pnl_usd=pnl_usd,
                    duration_bars=idx - open_pos.opened_bar_idx,
                ))
                stats["n_closes"] += 1
                open_pos = None
                last_emission_bar_global = idx  # cooldown apres close

        close_px = row.get("close")
        if close_px is None or pd.isna(close_px):
            continue
        date_iso = row.get("date_iso")
        mq_today = mq_by_date.get(date_iso)

        # 1) extract levels + detect zones at this bar
        levels = extract_levels_for_bar(row, mq_today)
        if verbose and idx % 1000 == 0:
            stats["level_counts"].append(len(levels))
        zones = detect_confluence_zones(levels, BUFFER_CONFLUENCE_TICKS, tick, close_px)
        stats["n_zones_detected_total"] += len(zones)

        # 2) touch detection (current bar)
        buffer_zone_pts = abs(close_px) * (BUFFER_ZONE_PCT / 100.0)
        for zmin, zmax, zlist, side in zones:
            touched = (close_px >= zmin - buffer_zone_pts) and (close_px <= zmax + buffer_zone_pts)
            if not touched:
                continue
            zid = _zone_id(zmin, zmax)
            if zid not in armed_zones:
                armed_zones[zid] = {
                    "touch_bar_idx": idx,
                    "side": side,
                    "zone_min": zmin,
                    "zone_max": zmax,
                    "levels": zlist,
                }
                stats["n_zones_touched"] += 1
                if verbose and idx < 50:
                    print(f"[{LOG_PREFIX_TOUCH}] idx={idx} ts={row['ts_event']} side={side} zone=[{zmin:.2f},{zmax:.2f}] n_lvl={len(zlist)} close={close_px}")

        # 3) confirmation check (bar t+1 par rapport au touch)
        if open_pos is None:
            for zid in list(armed_zones.keys()):
                az = armed_zones[zid]
                if az["touch_bar_idx"] >= idx:
                    continue                              # touched this same bar, attendre next
                # confirmation bar = idx (current)
                # garder en armed jusqu'a 3 bars max
                if idx - az["touch_bar_idx"] > 3:
                    del armed_zones[zid]
                    continue
                if not check_confirmation(row, az["side"], az["zone_min"], az["zone_max"], variant):
                    continue
                # Cooldown global
                if idx - last_emission_bar_global < COOLDOWN_BARS:
                    stats["n_pos_skipped_cooldown"] += 1
                    continue
                # Daily cap per zone
                key_cap = (date_iso, zid)
                if daily_emission_counts.get(key_cap, 0) >= MAX_PER_ZONE_PER_DAY:
                    stats["n_pos_skipped_dailycap"] += 1
                    continue
                # Build entry
                entry_price = float(close_px)
                sl, tp, tp_mode, sl_ticks, tp_ticks = compute_sl_tp(
                    row, az["side"], az["zone_min"], az["zone_max"], entry_price, tick
                )
                if sl_ticks <= 0 or tp_ticks <= 0:
                    continue
                cats = tuple(sorted({l.category for l in az["levels"]}))
                names = tuple(l.name for l in az["levels"])
                decision = EntryDecision(
                    side=az["side"],
                    n_levels=len(az["levels"]),
                    level_categories=cats,
                    level_names=names,
                    entry_price=entry_price,
                    sl_price=sl,
                    tp_price=tp,
                    sl_ticks=sl_ticks,
                    tp_ticks=tp_ticks,
                    tp_mode=tp_mode,
                    bar_idx=idx,
                    bar_ts=row["ts_event"],
                    variant=variant,
                )
                open_pos = OpenPosition(decision=decision, opened_bar_idx=idx)
                last_emission_bar_global = idx
                daily_emission_counts[key_cap] = daily_emission_counts.get(key_cap, 0) + 1
                stats["n_confirm_pass"] += 1
                stats["n_entries"] += 1
                if verbose and stats["n_entries"] <= 10:
                    print(f"[{LOG_PREFIX_ENTRY}] idx={idx} ts={row['ts_event']} side={az['side']} entry={entry_price:.2f} sl={sl:.2f} tp={tp:.2f} sl_t={sl_ticks} tp_t={tp_ticks} tp_mode={tp_mode} n_lvl={len(az['levels'])} cats={cats}")
                del armed_zones[zid]
                break       # 1 trade max ouvert
        else:
            stats["n_pos_skipped_open"] += 1

    return trades, stats


# ---------------------------------------------------------------------
# METRICS (PF, Sharpe, DSR Lopez)
# ---------------------------------------------------------------------
def compute_basic_metrics(trades: list) -> dict:
    if not trades:
        return {"n_trades": 0, "pf": 0.0, "sharpe": 0.0, "win_rate": 0.0,
                "pnl_total_usd": 0.0, "pnl_total_ticks": 0.0, "avg_ticks": 0.0}
    pnl_ticks = np.array([t.pnl_ticks for t in trades])
    pnl_usd = np.array([t.pnl_usd for t in trades])
    wins = pnl_ticks > 0
    win_sum = pnl_ticks[wins].sum()
    loss_sum = -pnl_ticks[~wins].sum()
    pf = float(win_sum / loss_sum) if loss_sum > 0 else float("inf")
    mu = float(pnl_ticks.mean())
    sd = float(pnl_ticks.std(ddof=1)) if len(pnl_ticks) > 1 else 0.0
    sharpe = mu / sd if sd > 0 else 0.0
    return {
        "n_trades": int(len(trades)),
        "pf": pf,
        "sharpe": float(sharpe),
        "win_rate": float(wins.sum() / len(wins)),
        "pnl_total_usd": float(pnl_usd.sum()),
        "pnl_total_ticks": float(pnl_ticks.sum()),
        "avg_ticks": float(mu),
    }


def deflated_sharpe(returns: np.ndarray, n_trials: int = 5) -> float:
    """DSR approximation Lopez AFML ch.11.
    Pour walk-forward, returns = sharpe par fold.
    n_trials = nombre de strategies testees (V11.0..V11.4 = 5).
    """
    if scstats is None or len(returns) < 3:
        return 0.0
    sr = returns.mean() / returns.std(ddof=1) if returns.std(ddof=1) > 0 else 0.0
    N = len(returns)
    # E[max SR] approx via Bailey & Lopez (2014)
    emc = 0.5772156649  # Euler-Mascheroni
    e_max = math.sqrt(2 * math.log(max(n_trials, 2))) * (1 - emc) + \
            math.sqrt(2 * math.log(max(n_trials, 2))) * emc / math.sqrt(2 * math.log(max(n_trials, 2)))
    skew = float(scstats.skew(returns, bias=False))
    kurt = float(scstats.kurtosis(returns, bias=False))
    denom = math.sqrt(max(1e-9, 1 - skew * sr + ((kurt - 1) / 4.0) * sr * sr))
    z = (sr - e_max) * math.sqrt(max(N - 1, 1)) / denom
    return float(scstats.norm.cdf(z))


def walk_forward_eval(trades: list, folds: int = WF_FOLDS, n_trials: int = 5) -> dict:
    """Decoupe trades en folds chronologiques, calcule metriques par fold."""
    if not trades:
        return {"n_folds_active": 0, "dsr": 0.0, "pf_median": 0.0, "sharpe_median": 0.0,
                "pf_min": 0.0, "n_trades_min": 0, "folds": []}
    trades_sorted = sorted(trades, key=lambda t: t.entry_ts)
    n = len(trades_sorted)
    fold_size = max(1, n // folds)
    folds_metrics = []
    for f in range(folds):
        start = f * fold_size
        end = (f + 1) * fold_size if f < folds - 1 else n
        slice_t = trades_sorted[start:end]
        m = compute_basic_metrics(slice_t)
        folds_metrics.append(m)
    sharpes = np.array([f["sharpe"] for f in folds_metrics if f["n_trades"] >= 2])
    pfs = [f["pf"] for f in folds_metrics if f["n_trades"] >= 2 and not math.isinf(f["pf"])]
    n_active = sum(1 for f in folds_metrics if f["n_trades"] >= 2)
    dsr = deflated_sharpe(sharpes, n_trials=n_trials) if len(sharpes) >= 3 else 0.0
    return {
        "n_folds_active": int(n_active),
        "dsr": float(dsr),
        "pf_median": float(np.median(pfs)) if pfs else 0.0,
        "sharpe_median": float(np.median(sharpes)) if len(sharpes) else 0.0,
        "pf_min": float(min(pfs)) if pfs else 0.0,
        "n_trades_min": int(min((f["n_trades"] for f in folds_metrics if f["n_trades"] >= 1),
                                 default=0)),
        "folds": folds_metrics,
    }


def detect_pattern_11(results_by_variant: dict) -> str:
    """Cf spec section 5.3."""
    statuses = {v: results_by_variant.get(v, {}).get("go", False) for v in VARIANTS}
    if all(statuses.values()):
        return "LEGITIME_ALL_GO"
    if statuses.get("V11.0") and not any(statuses[v] for v in VARIANTS[1:]):
        return "LEGITIME_BASELINE_ONLY"
    if statuses.get("V11.4") and not any(statuses[v] for v in VARIANTS[:-1]):
        return "SUSPECT_PATTERN_11"
    if not any(statuses.values()):
        return "ALL_NOGO"
    return "MIXED"


# ---------------------------------------------------------------------
# REPORT / OUTPUTS
# ---------------------------------------------------------------------
def trades_to_df(trades: list) -> pd.DataFrame:
    if not trades:
        return pd.DataFrame()
    rows = []
    for t in trades:
        rows.append({
            "variant": t.variant,
            "symbol": t.symbol,
            "side": t.side,
            "entry_ts": t.entry_ts,
            "exit_ts": t.exit_ts,
            "entry_price": t.entry_price,
            "exit_price": t.exit_price,
            "sl_price": t.sl_price,
            "tp_price": t.tp_price,
            "sl_ticks": t.sl_ticks,
            "tp_ticks": t.tp_ticks,
            "n_levels": t.n_levels,
            "level_categories": t.level_categories,
            "level_names": t.level_names,
            "tp_mode": t.tp_mode,
            "exit_reason": t.exit_reason,
            "pnl_ticks": t.pnl_ticks,
            "pnl_usd": t.pnl_usd,
            "duration_bars": t.duration_bars,
        })
    return pd.DataFrame(rows)


def evaluate_go(metrics: dict, wf: dict, trades: list) -> tuple:
    """Retourne (go_bool, reasons_list)."""
    reasons = []
    if metrics["n_trades"] < 100:
        reasons.append(f"n_trades<{100} ({metrics['n_trades']})")
    if wf["dsr"] < 0.95:
        reasons.append(f"DSR<0.95 ({wf['dsr']:.3f})")
    if wf["pf_median"] < 1.3:
        reasons.append(f"PF_median<1.3 ({wf['pf_median']:.2f})")
    if wf["sharpe_median"] < 1.0:
        reasons.append(f"Sharpe_median<1.0 ({wf['sharpe_median']:.2f})")
    if wf["pf_min"] < 0.8 and wf["pf_min"] > 0:
        reasons.append(f"PF_min<0.8 ({wf['pf_min']:.2f})")
    if wf["n_trades_min"] < 5:
        reasons.append(f"n_trades_min_fold<5 ({wf['n_trades_min']})")
    # concentration < 33% / single level cat
    if trades:
        from collections import Counter
        cat_counter = Counter()
        for t in trades:
            for c in t.level_categories.split(","):
                cat_counter[c] += 1
        total = sum(cat_counter.values())
        top_share = max(cat_counter.values()) / total if total else 0
        if top_share > 0.33:
            top_cat = cat_counter.most_common(1)[0][0]
            reasons.append(f"concentration>{33}% ({top_cat}={top_share:.0%})")
    return (len(reasons) == 0), reasons


# ---------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", choices=["NQ", "ES", "ALL"], default="ALL")
    ap.add_argument("--variant", choices=VARIANTS + ["ALL"], default="ALL")
    ap.add_argument("--quick", action="store_true", help="1 mois (mai 2026)")
    ap.add_argument("--start", default=PERIOD_START)
    ap.add_argument("--end", default=PERIOD_END)
    ap.add_argument("--out-dir", default=str(OUT_DIR))
    args = ap.parse_args()

    if args.quick:
        start = "2026-05-01"
        end = "2026-05-15"
    else:
        start, end = args.start, args.end

    symbols = ["NQ", "ES"] if args.symbol == "ALL" else [args.symbol]
    variants = VARIANTS if args.variant == "ALL" else [args.variant]

    print("=" * 70)
    print(f"Bot 4 backtest | period={start}->{end} | symbols={symbols} | variants={variants}")
    print("=" * 70)

    # Load MQ cache once
    print("\n[1/3] Loading MenthorQ cache...")
    mq_cache = load_menthorq_cache(MENTHORQ_DIR)
    n_days = len(mq_cache)
    print(f"  MQ cache: {n_days} days, sample dates: {sorted(mq_cache.keys())[:3]}...{sorted(mq_cache.keys())[-3:]}")

    # Per-symbol load + run
    all_trades = []
    results_by_variant = {v: {} for v in variants}

    for symbol in symbols:
        print(f"\n[2/3] Loading parquet {symbol} {start}->{end}...")
        df = load_parquet_period(symbol, start, end)
        if df.empty:
            print(f"  WARN: parquet empty for {symbol}")
            continue
        print(f"  Bars loaded: {len(df)} | TS [{df['ts_event'].iloc[0]} -> {df['ts_event'].iloc[-1]}]")

        # Stats levels (sample)
        sample_levels_counts = []
        sample_idx = np.linspace(0, len(df) - 1, min(200, len(df))).astype(int)
        for i in sample_idx:
            row = df.iloc[i].to_dict()
            d_iso = row.get("date_iso")
            mq_today = lookup_mq_for_date(mq_cache, d_iso, symbol)
            levels = extract_levels_for_bar(row, mq_today)
            sample_levels_counts.append(len(levels))
        print(f"  Levels per bar (sample 200): mean={np.mean(sample_levels_counts):.1f} median={np.median(sample_levels_counts):.0f} min={min(sample_levels_counts)} max={max(sample_levels_counts)}")

        for variant in variants:
            print(f"\n[3/3] Backtest {symbol} {variant}...")
            trades, stats = run_backtest(df, symbol, mq_cache, variant, verbose=args.quick)
            print(f"  Stats: zones_detected={stats['n_zones_detected_total']} zones_touched={stats['n_zones_touched']} confirm_pass={stats['n_confirm_pass']} entries={stats['n_entries']} closes={stats['n_closes']} skip_open={stats['n_pos_skipped_open']} skip_cooldown={stats['n_pos_skipped_cooldown']} skip_dailycap={stats['n_pos_skipped_dailycap']}")
            m = compute_basic_metrics(trades)
            print(f"  Metrics: n={m['n_trades']} pf={m['pf']:.2f} sharpe={m['sharpe']:.2f} wr={m['win_rate']:.0%} pnl=${m['pnl_total_usd']:.2f} avg_t={m['avg_ticks']:+.2f}")
            wf = walk_forward_eval(trades, folds=WF_FOLDS, n_trials=len(variants))
            print(f"  WF: dsr={wf['dsr']:.3f} pf_med={wf['pf_median']:.2f} shr_med={wf['sharpe_median']:.2f} pf_min={wf['pf_min']:.2f} n_min={wf['n_trades_min']} folds_active={wf['n_folds_active']}")
            go, reasons = evaluate_go(m, wf, trades)
            print(f"  Verdict: {'GO' if go else 'NOGO'} | reasons: {reasons or 'all_pass'}")
            all_trades.extend(trades)
            results_by_variant[variant][symbol] = {
                "go": go, "reasons": reasons, "metrics": m, "wf": wf, "stats": stats
            }

    # Pattern 11 detection (par symbol)
    print("\n" + "=" * 70)
    print("PATTERN 11 ANALYSIS")
    print("=" * 70)
    for symbol in symbols:
        if not any(symbol in results_by_variant[v] for v in variants):
            continue
        rbs = {v: results_by_variant[v].get(symbol, {}) for v in variants}
        verdict = detect_pattern_11(rbs)
        print(f"  {symbol}: {verdict}")

    # Output CSV (non-quick uniquement)
    if not args.quick:
        out_dir = Path(args.out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        for variant in variants:
            slice_t = [t for t in all_trades if t.variant == variant]
            if slice_t:
                df_t = trades_to_df(slice_t)
                csv_fp = out_dir / f"bot4_{variant.replace('.', '_')}_trades.csv"
                df_t.to_csv(csv_fp, index=False)
                print(f"  CSV: {csv_fp}")
        # Markdown summary
        md_fp = out_dir / "REPORT.md"
        with open(md_fp, "w", encoding="utf-8") as f:
            f.write("# Bot 4 — Backtest Report\n\n")
            f.write(f"Periode : {start} -> {end}\n")
            f.write(f"Symboles : {symbols}\n")
            f.write(f"Variantes : {variants}\n\n")
            for variant in variants:
                f.write(f"## {variant}\n\n")
                for symbol in symbols:
                    r = results_by_variant[variant].get(symbol, {})
                    if not r:
                        continue
                    m = r["metrics"]; wf = r["wf"]
                    f.write(f"### {symbol}\n\n")
                    f.write(f"- GO: **{'YES' if r['go'] else 'NO'}** | reasons: {r['reasons'] or 'all_pass'}\n")
                    f.write(f"- n_trades={m['n_trades']} pf={m['pf']:.2f} sharpe={m['sharpe']:.2f} wr={m['win_rate']:.0%}\n")
                    f.write(f"- DSR={wf['dsr']:.3f} pf_med={wf['pf_median']:.2f} shr_med={wf['sharpe_median']:.2f}\n")
                    f.write(f"- pnl_usd=${m['pnl_total_usd']:.2f}\n\n")
            f.write("\n## Pattern 11 analysis\n\n")
            for symbol in symbols:
                rbs = {v: results_by_variant[v].get(symbol, {}) for v in variants}
                f.write(f"- {symbol}: **{detect_pattern_11(rbs)}**\n")
        print(f"  Markdown: {md_fp}")

    print("\n" + "=" * 70)
    print("DONE.")


if __name__ == "__main__":
    main()
