"""
sessions_swings_engine.py — Bloc 3 #8-10 : Sessions + Swings + bonus ICT/SMC.

Reproduit les standards pro orderflow / Smart Money Concepts :
  NIVEAU 1 - Swings globaux significatifs (N=10, prominence 0.1%)
  NIVEAU 2 - Highs/Lows par session (Asia/London/US/After-hours)
  NIVEAU 3 - Opens de chaque session (avec DST auto via zoneinfo)
  NIVEAU 4 - Bonus ICT : Liquidity Sweep, Equal Highs/Lows, Premium/Discount

Convention sessions ET (DST-aware) :
  Asia        : 18:00-03:00 ET  (= 00:00-09:00 Paris ete, 23:00-08:00 Paris hiver)
  London      : 03:00-09:30 ET  (overlap Tokyo close + LDN cash open)
  US Cash     : 09:30-16:00 ET  (NYSE cash session)
  After-hours : 16:00-18:00 ET  (futures continue, cash close)

Auteur : Bloc 3 #8-10 (2026-04-27, post BN #1-12)
"""
from __future__ import annotations

from typing import Optional
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from extension_lines_manager import ExtensionLineBuffer

# Pattern try/except : 2 conventions sys.path (ROOT/ via -m, vs CORE/ direct CLI)
try:
    from CORE.constants import get_tick_size as _get_tick_size
except ImportError:
    from constants import get_tick_size as _get_tick_size

ET = ZoneInfo("America/New_York")
TICK_SIZE = 0.25  # default ES/NQ. MGC=0.10 — caller passe tick explicitement

# Session boundaries en minutes ET (DST-aware automatique via zoneinfo)
# Defaults ES/NQ (NYSE convention). Pour MGC=08:30 ET RTH gold COMEX, utiliser
# get_session_boundaries(symbol) depuis CORE/constants.py (Chantier 4 10/05/2026).
SESSION_ASIA_START = 18 * 60      # 18:00 ET (default ES/NQ)
SESSION_LONDON_START = 3 * 60     # 03:00 ET
SESSION_US_START = 9 * 60 + 30    # 09:30 ET (default ES/NQ — MGC=08:30)
SESSION_US_AFTER_START = 16 * 60  # 16:00 ET (default ES/NQ — MGC=13:30)

# Defaults dict pour passage aux sous-fonctions
_DEFAULT_BOUNDS = {
    "asia_start": SESSION_ASIA_START,
    "london_start": SESSION_LONDON_START,
    "us_start": SESSION_US_START,
    "us_after_start": SESSION_US_AFTER_START,
}

# Swing detection params
SWING_LOOKBACK = 10                # N bars de chaque cote
SWING_MIN_PROMINENCE_PCT = 0.1     # 0.1% du prix = ~6 ticks ES, ~27 ticks NQ

# Equal highs/lows threshold per-symbole
EQUAL_THRESHOLD_TICKS = {"ES": 5, "NQ": 10}

# Liquidity sweep window (N bars apres le break)
LIQUIDITY_SWEEP_WINDOW = 5


def _ts_to_et_mins(df: pd.DataFrame) -> pd.Series:
    """Convertit ts_event en minutes ET (DST-aware)."""
    if df["ts_event"].dt.tz is None:
        ts_et = df["ts_event"].dt.tz_localize("UTC").dt.tz_convert(ET)
    else:
        ts_et = df["ts_event"].dt.tz_convert(ET)
    return ts_et.dt.hour * 60 + ts_et.dt.minute, ts_et


def add_session_metadata_v2(df: pd.DataFrame, bounds: dict | None = None) -> pd.DataFrame:
    """
    Ajoute session_id + booleans is_in_*.

    Args:
        df: DataFrame avec ts_event
        bounds: dict avec keys asia_start/london_start/us_start/us_after_start
            (mins ET). Si None, utilise defaults ES/NQ (09:30 NYSE RTH).
            Pour MGC, passer get_session_boundaries("MGC") depuis constants.py.

    session_id codes (defaults ES/NQ) :
      0 = Asia (18:00-03:00 ET)
      1 = London (03:00-09:30 ET)
      2 = US Cash (09:30-16:00 ET)
      3 = US After-hours (16:00-18:00 ET)

    Pour MGC : Asia 19:00-03:00, London 03:00-08:30, US RTH 08:30-13:30,
    US After 13:30-19:00.
    """
    if bounds is None:
        bounds = _DEFAULT_BOUNDS
    asia_start = bounds["asia_start"]
    london_start = bounds["london_start"]
    us_start = bounds["us_start"]
    us_after_start = bounds["us_after_start"]

    df = df.copy()
    mins_et, ts_et = _ts_to_et_mins(df)
    df["mins_et"] = mins_et.values

    # session_id selon mins_et (utilise bounds per-symbole)
    sid = np.full(len(df), -1, dtype=np.int8)
    sid[(mins_et >= asia_start) | (mins_et < london_start)] = 0  # Asia
    sid[(mins_et >= london_start) & (mins_et < us_start)] = 1     # London
    sid[(mins_et >= us_start) & (mins_et < us_after_start)] = 2  # US Cash (RTH)
    sid[(mins_et >= us_after_start) & (mins_et < asia_start)] = 3  # US After
    df["session_id"] = sid
    df["is_in_asia"] = (sid == 0).astype("int8")
    df["is_in_london"] = (sid == 1).astype("int8")
    df["is_in_us_cash"] = (sid == 2).astype("int8")
    df["is_in_us_after"] = (sid == 3).astype("int8")

    # date_session_trading : jour de session (= date ET, sauf si on est apres asia_start -> jour suivant)
    # Permet de regrouper toutes les bars d'une session de trading (Asia + London + US + After d'un meme cycle)
    date_et = ts_et.dt.date
    # Si on est apres asia_start ET (= debut Asia du J+1), session_date = date_et + 1
    df["session_date"] = np.where(
        mins_et >= asia_start,
        (ts_et + pd.Timedelta(days=1)).dt.date,
        date_et,
    )
    return df


def add_session_highs_lows(df: pd.DataFrame, tick: float = TICK_SIZE) -> pd.DataFrame:
    """
    Calcule running highs/lows par session (Asia/London/US/After-hours).
    Reset quand session change (new session_date OU new session_id).

    Outputs (12 features) :
      asia_high, asia_low, london_high, london_low, us_high, us_low,
      after_high, after_low (PRIX -> exclude ML)
      dist_asia_high_pct, dist_asia_low_pct (ML)
      dist_london_high_pct, dist_london_low_pct
      dist_us_high_pct, dist_us_low_pct
      dist_after_high_pct, dist_after_low_pct
    """
    df = df.copy()
    if "session_id" not in df.columns:
        df = add_session_metadata_v2(df)

    n = len(df)
    high_arr = df["high"].values
    low_arr = df["low"].values
    close_arr = df["close"].values
    sid_arr = df["session_id"].values
    sdate_arr = df["session_date"].values

    # Running high/low par session (reset quand change)
    asia_h = np.full(n, np.nan)
    asia_l = np.full(n, np.nan)
    lon_h = np.full(n, np.nan)
    lon_l = np.full(n, np.nan)
    us_h = np.full(n, np.nan)
    us_l = np.full(n, np.nan)
    aft_h = np.full(n, np.nan)
    aft_l = np.full(n, np.nan)

    # Pour chaque session_date + session_id, accumuler running max/min
    # Mais simpler : track current per-session high/low, reset quand changes
    cur_session = (-1, None)  # (session_id, session_date)
    cur_h = np.nan
    cur_l = np.nan

    # Track highs/lows par session_date pour stockage
    # Dict {(sdate, sid) -> (h, l)} mis a jour iterativement
    session_hl = {}  # cumul pendant la session courante

    for i in range(n):
        sid = sid_arr[i]
        sdate = sdate_arr[i]
        h = high_arr[i]
        l = low_arr[i]
        key = (sdate, sid)

        if key not in session_hl:
            session_hl[key] = [h, l]
        else:
            if h > session_hl[key][0]:
                session_hl[key][0] = h
            if l < session_hl[key][1]:
                session_hl[key][1] = l

        # Pour chaque session, recuperer les valeurs courantes (= extreme atteint jusqu'a present)
        for s_target, arr_h, arr_l in [
            (0, asia_h, asia_l),
            (1, lon_h, lon_l),
            (2, us_h, us_l),
            (3, aft_h, aft_l),
        ]:
            k = (sdate, s_target)
            if k in session_hl:
                arr_h[i] = session_hl[k][0]
                arr_l[i] = session_hl[k][1]

    df["asia_high"] = asia_h
    df["asia_low"] = asia_l
    df["london_high"] = lon_h
    df["london_low"] = lon_l
    df["us_high"] = us_h
    df["us_low"] = us_l
    df["after_high"] = aft_h
    df["after_low"] = aft_l

    # Distances en pct (ML-usable)
    for prefix in ["asia", "london", "us", "after"]:
        df[f"dist_{prefix}_high_pct"] = ((close_arr - df[f"{prefix}_high"].values) / close_arr * 100).astype("float32")
        df[f"dist_{prefix}_low_pct"] = ((close_arr - df[f"{prefix}_low"].values) / close_arr * 100).astype("float32")
    return df


def add_session_opens(df: pd.DataFrame, bounds: dict | None = None) -> pd.DataFrame:
    """
    Opens de chaque session (concept ICT/SMC : prix d'ouverture = niveau cle).
      asia_open    = open de la 1ere barre Asia (defaults ES/NQ : 18:00 ET, MGC : 19:00 ET)
      london_open  = open 1ere barre London (03:00 ET universel)
      ny_open      = open 1ere barre US cash (defaults : 09:30 ET, MGC : 08:30 ET RTH gold)
      after_open   = open 1ere barre after-hours (defaults : 16:00 ET, MGC : 13:30 ET)

    Args:
        df: DataFrame avec ts_event, open, close
        bounds: dict per-symbole. Si None, defaults ES/NQ.

    Output (12 features) :
      asia_open, london_open, ny_open, after_open (PRIX -> exclude ML)
      dist_*_open_pct (ML, 4 features)
      above_*_open (booleans bias, 4 features)
    """
    if bounds is None:
        bounds = _DEFAULT_BOUNDS
    asia_start = bounds["asia_start"]
    london_start = bounds["london_start"]
    us_start = bounds["us_start"]
    us_after_start = bounds["us_after_start"]

    df = df.copy()
    if "session_id" not in df.columns:
        df = add_session_metadata_v2(df, bounds=bounds)

    open_arr = df["open"].values
    close_arr = df["close"].values
    mins_arr = df["mins_et"].values
    sdate_arr = df["session_date"].values

    n = len(df)
    asia_o = np.full(n, np.nan)
    lon_o = np.full(n, np.nan)
    ny_o = np.full(n, np.nan)
    aft_o = np.full(n, np.nan)

    # Track open par (sdate, target_minute)
    opens_dict = {}  # {(sdate, target_min) -> open_value}

    targets = [asia_start, london_start, us_start, us_after_start]
    for i in range(n):
        sdate = sdate_arr[i]
        m = mins_arr[i]
        # Stocke open de la 1ere bar atteignant chaque target
        for target in targets:
            key = (sdate, target)
            if m == target and key not in opens_dict:
                opens_dict[key] = open_arr[i]

        # Recupere opens de la session_date courante (bounds per-symbole)
        asia_o[i] = opens_dict.get((sdate, asia_start), np.nan)
        lon_o[i] = opens_dict.get((sdate, london_start), np.nan)
        ny_o[i] = opens_dict.get((sdate, us_start), np.nan)
        aft_o[i] = opens_dict.get((sdate, us_after_start), np.nan)

    df["asia_open"] = asia_o
    df["london_open"] = lon_o
    df["ny_open"] = ny_o
    df["after_open"] = aft_o

    for prefix, col in [("asia", asia_o), ("london", lon_o), ("ny", ny_o), ("after", aft_o)]:
        df[f"dist_{prefix}_open_pct"] = ((close_arr - col) / close_arr * 100).astype("float32")
        df[f"above_{prefix}_open"] = (close_arr > col).astype("int8")
    return df


def add_swing_features_v2(df: pd.DataFrame, n_bars: int = SWING_LOOKBACK,
                           min_prominence_pct: float = SWING_MIN_PROMINENCE_PCT) -> pd.DataFrame:
    """
    Bloc 3 #8 Swings significatifs (NIVEAUX IMPORTANTS uniquement).

    Definition : bar i est swing si extreme local sur fenetre [i-N, i+N]
    AVEC prominence (amplitude vs autre side) >= min_prominence_pct du prix.

    Convention Jackson : "que un niveau IMPORTANT, pas tous les pivots".

    LOOKAHEAD : detection necessite N bars apres -> suffix `_lag{N}`.

    Outputs (8 features) :
      swing_high_active_lag10 : 1 si la bar est un swing high significatif
      swing_low_active_lag10  : 1 si swing low
      dist_last_swing_high_pct : distance close vers dernier swing high (en %)
      dist_last_swing_low_pct  : distance close vers dernier swing low
      bars_since_last_swing_high : nb bars depuis dernier swing high
      bars_since_last_swing_low  : idem
      last_swing_high_session : session_id du dernier swing high (0/1/2/3)
      last_swing_low_session  : session_id du dernier swing low
    """
    df = df.copy()
    if "session_id" not in df.columns:
        df = add_session_metadata_v2(df)

    n = len(df)
    high = df["high"].values
    low = df["low"].values
    close = df["close"].values
    sid = df["session_id"].values

    swing_h = np.zeros(n, dtype=np.int8)
    swing_l = np.zeros(n, dtype=np.int8)

    for i in range(n_bars, n - n_bars):
        win_h = high[i - n_bars : i + n_bars + 1]
        win_l = low[i - n_bars : i + n_bars + 1]

        if high[i] >= win_h.max() and high[i] > 0:
            prominence = (high[i] - win_l.min()) / close[i] * 100
            if prominence >= min_prominence_pct:
                swing_h[i] = 1

        if low[i] <= win_l.min() and low[i] > 0:
            prominence = (win_h.max() - low[i]) / close[i] * 100
            if prominence >= min_prominence_pct:
                swing_l[i] = 1

    # Last swing high/low + bars_since + session_id du dernier swing
    last_h_price = np.full(n, np.nan)
    last_l_price = np.full(n, np.nan)
    bars_since_h = np.full(n, -1, dtype=np.int32)
    bars_since_l = np.full(n, -1, dtype=np.int32)
    last_h_session = np.full(n, -1, dtype=np.int8)
    last_l_session = np.full(n, -1, dtype=np.int8)

    cur_h_price = np.nan
    cur_h_bar = -1
    cur_h_sess = -1
    cur_l_price = np.nan
    cur_l_bar = -1
    cur_l_sess = -1

    for i in range(n):
        if swing_h[i]:
            cur_h_price = high[i]
            cur_h_bar = i
            cur_h_sess = sid[i]
        if swing_l[i]:
            cur_l_price = low[i]
            cur_l_bar = i
            cur_l_sess = sid[i]
        last_h_price[i] = cur_h_price
        last_l_price[i] = cur_l_price
        if cur_h_bar >= 0:
            bars_since_h[i] = i - cur_h_bar
        if cur_l_bar >= 0:
            bars_since_l[i] = i - cur_l_bar
        last_h_session[i] = cur_h_sess
        last_l_session[i] = cur_l_sess

    df["swing_high_active_lag10"] = swing_h
    df["swing_low_active_lag10"] = swing_l
    df["dist_last_swing_high_pct"] = ((close - last_h_price) / close * 100).astype("float32")
    df["dist_last_swing_low_pct"] = ((close - last_l_price) / close * 100).astype("float32")
    df["bars_since_last_swing_high"] = bars_since_h
    df["bars_since_last_swing_low"] = bars_since_l
    df["last_swing_high_session"] = last_h_session
    df["last_swing_low_session"] = last_l_session

    # Helpers internes (a drop avant write si exclude ML)
    df["_last_swing_high_price"] = last_h_price
    df["_last_swing_low_price"] = last_l_price
    return df


def add_liquidity_sweep(df: pd.DataFrame, window: int = LIQUIDITY_SWEEP_WINDOW) -> pd.DataFrame:
    """
    NIVEAU 4 BONUS - Liquidity Sweep detection (concept ICT pro).

    Pattern : prix casse un swing high/low recent puis revient sous/sur dans N bars.
    = stop hunt + reversal = setup pro tres puissant.

    Outputs (2 features) :
      liquidity_sweep_high : 1 si bar a casse swing_high recent puis close <= swing_high apres window bars
      liquidity_sweep_low  : 1 si bar a casse swing_low recent puis close >= swing_low apres window bars
    """
    df = df.copy()
    if "_last_swing_high_price" not in df.columns:
        # Necessite swing features
        return df

    n = len(df)
    high = df["high"].values
    low = df["low"].values
    close = df["close"].values
    swing_h_price = df["_last_swing_high_price"].values
    swing_l_price = df["_last_swing_low_price"].values

    sweep_h = np.zeros(n, dtype=np.int8)
    sweep_l = np.zeros(n, dtype=np.int8)

    for i in range(n):
        sh = swing_h_price[i]
        sl = swing_l_price[i]

        # Sweep high : bar i a high > swing_high (= casse), AND close[i+window] < swing_high (= reversal)
        if not np.isnan(sh) and high[i] > sh:
            check_idx = min(i + window, n - 1)
            if close[check_idx] < sh:
                sweep_h[i] = 1

        # Sweep low : bar i a low < swing_low (= casse), AND close[i+window] > swing_low (= reversal)
        if not np.isnan(sl) and low[i] < sl:
            check_idx = min(i + window, n - 1)
            if close[check_idx] > sl:
                sweep_l[i] = 1

    df["liquidity_sweep_high_lag5"] = sweep_h
    df["liquidity_sweep_low_lag5"] = sweep_l
    return df


def add_equal_swings(df: pd.DataFrame, symbol: str = "ES",
                      tick: float = TICK_SIZE) -> pd.DataFrame:
    """
    NIVEAU 4 BONUS - Equal Highs/Lows (concept ICT/SMC).

    Detecte 2 swings consecutifs (high ou low) tres proches en prix
    (< threshold ticks) = double resistance/support liquidity.

    Outputs (2 features) :
      equal_highs_detected : 1 si dernier swing high <= seuil ticks du precedent
      equal_lows_detected  : 1 si dernier swing low <= seuil ticks du precedent
    """
    df = df.copy()
    sym = symbol.upper().split(".")[0]
    threshold_ticks = EQUAL_THRESHOLD_TICKS.get(sym, 10)
    threshold_pts = threshold_ticks * tick

    n = len(df)
    swing_h = df["swing_high_active_lag10"].values if "swing_high_active_lag10" in df.columns else np.zeros(n)
    swing_l = df["swing_low_active_lag10"].values if "swing_low_active_lag10" in df.columns else np.zeros(n)
    high = df["high"].values
    low = df["low"].values

    eq_h = np.zeros(n, dtype=np.int8)
    eq_l = np.zeros(n, dtype=np.int8)

    prev_swing_h_price = np.nan
    prev_swing_l_price = np.nan

    for i in range(n):
        if swing_h[i]:
            if not np.isnan(prev_swing_h_price) and abs(high[i] - prev_swing_h_price) <= threshold_pts:
                eq_h[i] = 1
            prev_swing_h_price = high[i]
        if swing_l[i]:
            if not np.isnan(prev_swing_l_price) and abs(low[i] - prev_swing_l_price) <= threshold_pts:
                eq_l[i] = 1
            prev_swing_l_price = low[i]

    df["equal_highs_detected"] = eq_h
    df["equal_lows_detected"] = eq_l
    return df


# BN bonus Spike Origin (post-news mean reversion)
SPIKE_ROC_THRESHOLD_PCT = 0.10  # 0.1% en N bars = ~30 ticks ES, ~135 ticks NQ
SPIKE_WINDOW_BARS = 3            # 3 bars (3 min)


def add_spike_origin_features(df: pd.DataFrame,
                                threshold_pct: float = SPIKE_ROC_THRESHOLD_PCT,
                                window: int = SPIKE_WINDOW_BARS,
                                cluster_pct: float = 0.2) -> pd.DataFrame:
    """
    BN bonus Spike Origin (concept post-news mean reversion).

    Detection : ROC sur N bars >= seuil (mouvement violent en peu de temps).
      ROC_N = abs(close[i] - close[i-N]) / close[i-N] * 100

    Origin = open de la 1ere bar du spike (= prix avant mouvement)
      = close[i-N] (= close juste avant le spike)
      OU plus precis : open[i-N+1] (1ere bar du spike)
      Choix : open[i-N+1] (= debut du mouvement violent)

    Logique trading : marche revient typiquement combler la "fair value gap"
    creee par le spike (= liquidite asymetrique laissee non-completee).

    Extension Lines : zone tracee au prix d'origine, persiste jusqu'a touche.

    Convention SC : detection necessite N bars apres -> suffix `_lag{N}`.

    4 features generees :
      spike_detected_lag3 : 1 si spike vient de finir sur cette bar
      n_spike_origins_active : count zones spike non touchees
      dist_last_spike_origin_pct : distance close vers dernier spike origin actif
      bars_since_last_spike : nb bars depuis dernier spike detecte
      n_spike_origins_cluster_within_0_2pct : cluster local zones spike actives
    """
    df = df.copy()
    n = len(df)
    close = df["close"].values
    open_arr = df["open"].values
    high = df["high"].values
    low = df["low"].values

    spike_det = np.zeros(n, dtype=np.int8)
    n_active = np.zeros(n, dtype=np.int32)
    dist_nearest = np.full(n, np.nan, dtype=np.float64)
    bars_since = np.full(n, -1, dtype=np.int32)
    n_cluster = np.zeros(n, dtype=np.int32)

    # Buffer Extension Lines (utilise side='buy' arbitraire car spike origin est bidirectionnel)
    buf = ExtensionLineBuffer()
    last_spike_bar = -1

    for i in range(n):
        # 1. UPDATE buffer : deactivate zones touchees
        buf.update_with_bar(i, low[i], high[i])

        # 2. DETECT spike : ROC sur fenetre [i-N, i] >= threshold
        if i >= window and close[i - window] > 0:
            roc = abs(close[i] - close[i - window]) / close[i - window] * 100
            if roc >= threshold_pct:
                spike_det[i] = 1
                # Origin = open de la 1ere bar du spike (= bar i-N+1)
                # Si window=3, origin = open[i-2]
                origin_idx = max(i - window + 1, 0)
                origin_price = float(open_arr[origin_idx])
                buf.add_zone(i, [origin_price], "buy")
                last_spike_bar = i

        # 3. FEATURES count + nearest + cluster
        n_active[i] = sum(1 for z in buf.zones if z.active)
        cls = close[i]

        # Distance signed vers nearest active zone
        active_zones = [z for z in buf.zones if z.active]
        if active_zones:
            distances = []
            for z in active_zones:
                if cls < z.min_price:
                    d = z.min_price - cls
                elif cls > z.max_price:
                    d = -(cls - z.max_price)
                else:
                    d = 0
                distances.append(d)
            d_min = min(distances, key=abs)
            if cls > 0:
                dist_nearest[i] = (d_min / cls) * 100

        # Cluster local
        if cls > 0:
            cluster_range = cls * (cluster_pct / 100)
            cluster_low = cls - cluster_range
            cluster_high = cls + cluster_range
            n_cluster[i] = sum(
                1 for z in buf.zones
                if z.active and cluster_low <= z.min_price <= cluster_high
            )

        if last_spike_bar >= 0:
            bars_since[i] = i - last_spike_bar

    df["spike_detected_lag3"] = spike_det
    df["n_spike_origins_active"] = n_active
    df["dist_last_spike_origin_pct"] = dist_nearest
    df["bars_since_last_spike"] = bars_since
    df["n_spike_origins_cluster_within_0_2pct"] = n_cluster
    return df


def add_premium_discount(df: pd.DataFrame) -> pd.DataFrame:
    """
    NIVEAU 4 BONUS - Premium/Discount zone (concept ICT/SMC).

    Premium = prix dans top 50% du range jour courant
    Discount = prix dans bottom 50%

    Range jour = sess_high - sess_low (deja code dans phase_b_helpers).

    Outputs (3 features) :
      pct_in_range : position close dans [sess_low, sess_high], 0-100% (50% = midpoint)
      premium_zone : 1 si pct_in_range > 50%
      discount_zone : 1 si pct_in_range < 50%
    """
    df = df.copy()
    if "sess_high" not in df.columns or "sess_low" not in df.columns:
        # Sera calcule par phase_b_helpers.add_session_high_low
        return df

    close = df["close"].values
    sh = df["sess_high"].values
    sl = df["sess_low"].values

    rng = sh - sl
    rng_safe = np.where(rng > 0, rng, np.nan)
    pct = (close - sl) / rng_safe * 100
    pct = np.where(np.isnan(pct), 50, pct).clip(0, 100)

    df["pct_in_range"] = pct.astype("float32")
    df["premium_zone"] = (pct > 50).astype("int8")
    df["discount_zone"] = (pct < 50).astype("int8")
    return df


# ═══════════════════════════════════════════════════════════════════════════════
# PIPELINE COMPLETE
# ═══════════════════════════════════════════════════════════════════════════════

SESSIONS_SWINGS_GENERATED = {
    # Session metadata
    "session_id", "is_in_asia", "is_in_london", "is_in_us_cash", "is_in_us_after",
    "session_date", "mins_et",
    # Session highs/lows (PRIX -> exclude ML, distances ML)
    "asia_high", "asia_low", "london_high", "london_low",
    "us_high", "us_low", "after_high", "after_low",
    "dist_asia_high_pct", "dist_asia_low_pct",
    "dist_london_high_pct", "dist_london_low_pct",
    "dist_us_high_pct", "dist_us_low_pct",
    "dist_after_high_pct", "dist_after_low_pct",
    # Session opens
    "asia_open", "london_open", "ny_open", "after_open",
    "dist_asia_open_pct", "dist_london_open_pct", "dist_ny_open_pct", "dist_after_open_pct",
    "above_asia_open", "above_london_open", "above_ny_open", "above_after_open",
    # Swings significatifs
    "swing_high_active_lag10", "swing_low_active_lag10",
    "dist_last_swing_high_pct", "dist_last_swing_low_pct",
    "bars_since_last_swing_high", "bars_since_last_swing_low",
    "last_swing_high_session", "last_swing_low_session",
    "_last_swing_high_price", "_last_swing_low_price",  # internes
    # Liquidity Sweep + Equal swings + Premium/Discount
    "liquidity_sweep_high_lag5", "liquidity_sweep_low_lag5",
    "equal_highs_detected", "equal_lows_detected",
    "pct_in_range", "premium_zone", "discount_zone",
    # Spike Origin (post-news mean reversion)
    "spike_detected_lag3", "n_spike_origins_active",
    "dist_last_spike_origin_pct", "bars_since_last_spike",
    "n_spike_origins_cluster_within_0_2pct",
}


def apply_sessions_swings(df: pd.DataFrame, symbol: str = "ES") -> pd.DataFrame:
    """Pipeline complet Bloc 3 #8-10 : Sessions + Swings + bonus ICT/SMC.

    symbol : utilise pour :
      - tick_size (MGC=0.10 vs ES/NQ=0.25) propage aux helpers tick-aware
        (add_session_highs_lows, add_equal_swings)
      - session boundaries (Chantier 4 10/05/2026) : ES/NQ=09:30 NYSE RTH,
        MGC=08:30 COMEX RTH gold. Propage a add_session_metadata_v2 et
        add_session_opens. Cause racine fix NaN 71.9% cash sur MGC.
    """
    tick = _get_tick_size(symbol)

    # Charge boundaries per-symbole (Chantier 4 fix sessions Gold)
    try:
        from CORE.constants import get_session_boundaries
    except ImportError:
        from constants import get_session_boundaries
    bounds = get_session_boundaries(symbol)

    df = df.copy()
    drop_existing = [c for c in SESSIONS_SWINGS_GENERATED if c in df.columns]
    if drop_existing:
        df = df.drop(columns=drop_existing)

    df = add_session_metadata_v2(df, bounds=bounds)
    df = add_session_highs_lows(df, tick=tick)
    df = add_session_opens(df, bounds=bounds)
    df = add_swing_features_v2(df)
    df = add_liquidity_sweep(df)
    df = add_equal_swings(df, symbol=symbol, tick=tick)
    df = add_premium_discount(df)
    df = add_spike_origin_features(df)
    return df
