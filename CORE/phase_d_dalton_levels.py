"""
phase_d_dalton_levels.py — Phase D : Niveaux Dalton hedge manuel Jackson.

Reproduit en V4-natif les niveaux Market Profile que Jackson utilise dans son
hedge manuel : pVWAP + pSD bands, Naked POC tracker, Single Prints, Excess.

Concepts (Dalton "Mind over Markets" + Steidlmayer):

1. **pVWAP + pSD bands** (6 features)
   - VWAP de la session veille + ses SD+1/-1
   - Edge : zones de retest J+1 souvent reactives

2. **Naked POC** (4 features)
   - pVPOC, p2VPOC, p3VPOC non-retestes
   - Edge : ~70% retest dans 5-10 jours (Dalton, edgeful)
   - Pattern Extension Lines : la zone reste "active" tant que prix ne traverse pas

3. **Single Prints** (3 features)
   - Bucket de prix touche peu de fois (= 1 TPO Dalton classic, adapte 1m bars)
   - Edge : >70% retest dans sessions suivantes

4. **Excess (vrai tail)** (4 features)
   - High/low avec tail >= 2 TPOs sans acceptance
   - Edge directionnel inverse de poor_high (Dalton ch.5)
   - Excess high = top probable, excess low = bottom probable

Total : 17 features ML-usables.

Convention V4 :
  - Toutes distances en _pct (ML-usable, pas de fuite instrument)
  - Niveaux raw (pVWAP, naked POC prices) en helpers internes
  - Session = session_date_trading (CME 18:00 ET cutoff)

Auteur : Phase D V4 (2026-04-28)
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from constants import DEFAULT_TICK_SIZE
from extension_lines_manager import ExtensionLineBuffer


# Constantes Dalton calibrees
SINGLE_PRINT_MAX_TPO = 2  # bucket touche <=2 bars 1m = single print V4 (Dalton classic 30m = 1 TPO)
EXCESS_TAIL_MIN_TPO = 2  # >= 2 TPO de tail = excess Dalton
NAKED_POC_LOOKBACK_DAYS = 5  # tracker pVPOC sur les N derniers jours non-retestes
NAKED_POC_TOLERANCE_TICKS = 1  # tolerance retest = +/- 1 tick


# ═══════════════════════════════════════════════════════════════════════════════
# Bloc 1 : pVWAP + pSD bands
# ═══════════════════════════════════════════════════════════════════════════════

def add_pvwap_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Calcule pVWAP, pVWAP_SD+1, pVWAP_SD-1 (VWAP veille).

    Strategie :
      1. Pour chaque session J, recuperer le VWAP final (last bar) de session J-1
      2. Idem pour SD bands +1/-1 (last bar de J-1)
      3. Broadcast sur toutes les bars de session J
      4. Calculer distances normalisees ML-usable

    Requis : vwap_d, vwap_d_sd1u, vwap_d_sd1d, session_date_trading, close.

    Features generees (6) :
      - pvwap, pvwap_sd1u, pvwap_sd1d (helpers PRIX absolus, drop ML)
      - dist_pvwap_pct, dist_pvwap_sd1u_pct, dist_pvwap_sd1d_pct (ML-usable)
    """
    df = df.copy()
    required = ["vwap_d", "vwap_d_sd1u", "vwap_d_sd1d", "session_date_trading", "close"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise KeyError(f"[Phase D pVWAP] manquant : {missing}")

    # Pour chaque session, recuperer la derniere valeur de vwap_d / sd1u / sd1d
    sess_eod = df.groupby("session_date_trading")[["vwap_d", "vwap_d_sd1u", "vwap_d_sd1d"]].last()
    sess_eod = sess_eod.sort_index()

    # Mapper session J -> EOD de session J-1 via shift
    sess_eod_prev = sess_eod.shift(1)
    sess_eod_prev.columns = ["pvwap", "pvwap_sd1u", "pvwap_sd1d"]

    # Broadcast sur toutes les bars
    df = df.merge(
        sess_eod_prev,
        how="left",
        left_on="session_date_trading",
        right_index=True,
    )

    # Distances normalisees ML
    close_safe = df["close"].replace(0, np.nan)
    df["dist_pvwap_pct"] = ((df["close"] - df["pvwap"]) / close_safe * 100).astype("float32")
    df["dist_pvwap_sd1u_pct"] = ((df["close"] - df["pvwap_sd1u"]) / close_safe * 100).astype("float32")
    df["dist_pvwap_sd1d_pct"] = ((df["close"] - df["pvwap_sd1d"]) / close_safe * 100).astype("float32")
    df["pvwap"] = df["pvwap"].astype("float32")
    df["pvwap_sd1u"] = df["pvwap_sd1u"].astype("float32")
    df["pvwap_sd1d"] = df["pvwap_sd1d"].astype("float32")
    return df


# ═══════════════════════════════════════════════════════════════════════════════
# Bloc 2 : Naked POC tracker
# ═══════════════════════════════════════════════════════════════════════════════

def add_naked_poc_features(
    df: pd.DataFrame,
    lookback_days: int = NAKED_POC_LOOKBACK_DAYS,
    tolerance_ticks: int = NAKED_POC_TOLERANCE_TICKS,
    tick: float = DEFAULT_TICK_SIZE,
) -> pd.DataFrame:
    """
    Track les POC des N dernieres sessions qui n'ont PAS ete retestes.

    Algorithme :
      1. Pour chaque session J-1, J-2, ..., J-N : recuperer prev_vpoc (deja en V4)
      2. Pour chaque bar i de la session J, verifier si bar.low <= prev_vpoc <= bar.high
         (avec tolerance_ticks)
      3. Si touche -> retire le POC du tracker
      4. Naked POC actifs = ceux jamais retestes

    Features generees (4) :
      - n_naked_poc_active (count actifs sur les lookback_days derniers jours)
      - dist_naked_poc_nearest_pct (distance signed au plus proche)
      - bars_since_naked_poc_age_max (age en jours du plus vieux naked POC actif)
      - n_naked_poc_within_0_5pct (count cluster proche close)
    """
    df = df.copy()
    required = ["session_date_trading", "high", "low", "close"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise KeyError(f"[Phase D Naked POC] manquant : {missing}")
    if "prev_vpoc" not in df.columns:
        raise KeyError("[Phase D Naked POC] prev_vpoc manquant (Phase B helpers requis)")

    # Recuperer le prev_vpoc final par session (le pVPOC pour la session suivante)
    sess_pvpoc = df.groupby("session_date_trading")["prev_vpoc"].first()
    # Pour chaque session J, le prev_vpoc est le POC de J-1.
    # Donc si on track les POC J-1, J-2, ..., J-N pour la session J actuelle :
    #   sess_dates[J-1] -> prev_vpoc[J] (POC de J-1)
    #   sess_dates[J-2] -> prev_vpoc[J-1]
    #   etc.
    sess_pvpoc = sess_pvpoc.sort_index()

    sess_dates = sorted(sess_pvpoc.index.unique())

    n = len(df)
    n_active = np.zeros(n, dtype=np.int32)
    dist_nearest = np.full(n, np.nan, dtype=np.float64)
    age_max = np.zeros(n, dtype=np.int32)
    n_cluster = np.zeros(n, dtype=np.int32)

    tolerance = tolerance_ticks * tick
    high_arr = df["high"].values
    low_arr = df["low"].values
    close_arr = df["close"].values

    # Tracker de POC actifs : list of (poc_price, age_days, formed_session_date)
    # On itere par session pour init le tracker correctement
    df = df.reset_index(drop=True)
    sess_groups = df.groupby("session_date_trading", sort=True)

    for cur_sess_date, sess_df in sess_groups:
        cur_sess_idx_in_list = sess_dates.index(cur_sess_date) if cur_sess_date in sess_dates else -1
        # Construire la liste des POC J-1, J-2, ..., J-N a tester comme naked
        active_pocs = []  # list of (poc_price, age_days)
        for k in range(1, lookback_days + 1):
            past_idx = cur_sess_idx_in_list - k
            if past_idx < 0:
                break
            past_date = sess_dates[past_idx]
            past_pvpoc = sess_pvpoc.get(past_date)
            if pd.isna(past_pvpoc):
                continue
            active_pocs.append([float(past_pvpoc), k])  # [price, age_days]

        bars_in_sess = sess_df.index.to_numpy()
        for bar_i in bars_in_sess:
            bar_high = high_arr[bar_i]
            bar_low = low_arr[bar_i]
            cls = close_arr[bar_i]

            # Retirer les POC retestes par cette bar
            active_pocs = [
                p for p in active_pocs
                if not (bar_low - tolerance <= p[0] <= bar_high + tolerance)
            ]

            n_active[bar_i] = len(active_pocs)
            if active_pocs:
                # Plus proche en valeur absolue
                distances = [(p[0] - cls, p[1]) for p in active_pocs]
                d_min, _ = min(distances, key=lambda x: abs(x[0]))
                if cls > 0:
                    dist_nearest[bar_i] = (d_min / cls) * 100
                age_max[bar_i] = max(p[1] for p in active_pocs)
                # Cluster +/- 0.5%
                cluster_low = cls * 0.995
                cluster_high = cls * 1.005
                n_cluster[bar_i] = sum(
                    1 for p in active_pocs if cluster_low <= p[0] <= cluster_high
                )

    df["n_naked_poc_active"] = n_active.astype("int32")
    df["dist_naked_poc_nearest_pct"] = dist_nearest.astype("float32")
    df["naked_poc_age_max_days"] = age_max.astype("int32")
    df["n_naked_poc_within_0_5pct"] = n_cluster.astype("int32")
    return df


# ═══════════════════════════════════════════════════════════════════════════════
# Bloc 3 : Single Prints
# ═══════════════════════════════════════════════════════════════════════════════

def add_single_prints_features(
    df: pd.DataFrame,
    trades_df: pd.DataFrame,
    max_tpo: int = SINGLE_PRINT_MAX_TPO,
    tick: float = DEFAULT_TICK_SIZE,
) -> pd.DataFrame:
    """
    Detecte les single prints intra-session (= prix touche <= max_tpo bars).

    Strategie V4 (adaptee pour bars 1m) :
      1. Pour chaque session, compter le nombre de bars distinctes ou chaque
         prix bucket a ete touche (high >= price >= low)
      2. Single print = bucket touche <= max_tpo fois sur la session
      3. Detecter EOD pour la session courante
      4. Broadcast sur toutes les bars de la session (= EOD value)

    Features generees (3) :
      - n_single_prints_session (count single prints sur session courante)
      - dist_single_print_nearest_pct (distance close vers le plus proche)
      - has_single_print_above (boolean = il y a un SP au-dessus du close ?)

    NOTE : ces features sont des "EOD broadcast" similaires aux pdh/pdl, MAIS
    elles representent l'etat de la session J-1 (pas lookahead). En effet,
    on calcule sur trades_df de la session ET utilise pour session J+1.
    """
    df = df.copy()
    required = ["session_date_trading", "close"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise KeyError(f"[Phase D Single Prints] manquant : {missing}")

    if trades_df is None or trades_df.empty:
        # Fallback : init a 0 / NaN
        df["n_single_prints_session"] = 0
        df["dist_single_print_nearest_pct"] = np.nan
        df["has_single_print_above"] = 0
        return df

    # Pour chaque session, identifier les single prints de la session PRECEDENTE
    # (utilisable J+1 sans lookahead)
    sess_dates = sorted(df["session_date_trading"].unique())

    # Compter pour chaque session-bucket (bar, price_bucket) les visites
    df_sess = df[["session_date_trading", "high", "low"]].copy()
    df_sess["bar_id"] = df_sess.index

    # Pour chaque bar, lister les buckets touches : [low, high] step tick
    # Approche vectorisee : pour chaque bar generer la grid de buckets touches
    # FIX 28/04 (quality-auditor) : normaliser n_single_prints par n_total_buckets
    # session pour eliminer fuite instrument (NQ 1745 vs ES 365 buckets).
    # FIX 28/04 v4 (Jackson) : ajout vue ZONE (regroupe single prints contigus
    # = signal de mouvement impulsif Dalton, plus puissant que niveaux isoles).
    sp_per_session = {}  # session_date -> (single_prints_list, n_total_buckets, zones)

    for sess_date, sess_grp in df_sess.groupby("session_date_trading"):
        bucket_counts: dict[float, int] = {}
        for _, row in sess_grp.iterrows():
            if pd.isna(row["high"]) or pd.isna(row["low"]):
                continue
            low_bucket = round(row["low"] / tick) * tick
            high_bucket = round(row["high"] / tick) * tick
            n_buckets = int(round((high_bucket - low_bucket) / tick)) + 1
            for k in range(n_buckets):
                price = low_bucket + k * tick
                bucket_counts[price] = bucket_counts.get(price, 0) + 1
        # Single prints = buckets touches <= max_tpo fois
        single_prints = sorted([p for p, c in bucket_counts.items() if c <= max_tpo])
        n_total_buckets = max(len(bucket_counts), 1)

        # ZONES : grouper single prints contigus (>= 2 ticks consecutifs)
        zones = []  # list of (zone_low, zone_high, width_ticks)
        if single_prints:
            current = [single_prints[0]]
            for p in single_prints[1:]:
                if p - current[-1] <= tick * 1.5:  # tolerance arrondi flottant
                    current.append(p)
                else:
                    if len(current) >= 2:  # zone valide >= 2 ticks contigus
                        zones.append((current[0], current[-1], len(current)))
                    current = [p]
            if len(current) >= 2:
                zones.append((current[0], current[-1], len(current)))

        sp_per_session[sess_date] = (single_prints, n_total_buckets, zones)

    # Mapper session J -> single prints + zones de session J-1 (broadcast J+1)
    sess_to_prev_sp = {}
    for i, d in enumerate(sess_dates):
        if i > 0:
            sess_to_prev_sp[d] = sp_per_session.get(sess_dates[i - 1], ([], 1, []))
        else:
            sess_to_prev_sp[d] = ([], 1, [])

    # Compute features par bar
    n = len(df)
    n_sp_pct = np.zeros(n, dtype=np.float32)
    dist_nearest = np.full(n, np.nan, dtype=np.float64)
    has_above = np.zeros(n, dtype=np.int8)
    # Vue ZONE (FIX 28/04 v4)
    n_zones = np.zeros(n, dtype=np.int32)
    max_zone_width_ticks = np.zeros(n, dtype=np.int32)  # helper raw (drop ML)
    dist_zone_nearest = np.full(n, np.nan, dtype=np.float64)

    close_arr = df["close"].values
    sess_arr = df["session_date_trading"].values

    for i in range(n):
        sess = sess_arr[i]
        sps, n_total_buckets, zones = sess_to_prev_sp.get(sess, ([], 1, []))
        n_sp_pct[i] = len(sps) / max(n_total_buckets, 1)
        if sps and close_arr[i] > 0:
            cls = close_arr[i]
            distances = [p - cls for p in sps]
            d_min = min(distances, key=abs)
            dist_nearest[i] = (d_min / cls) * 100
            has_above[i] = 1 if any(p > cls for p in sps) else 0
        # Features ZONE
        n_zones[i] = len(zones)
        if zones:
            max_zone_width_ticks[i] = max(z[2] for z in zones)
            if close_arr[i] > 0:
                cls = close_arr[i]
                # Distance signed au CENTRE de la zone la plus proche
                zone_distances = []
                for z_low, z_high, _ in zones:
                    z_center = (z_low + z_high) / 2.0
                    zone_distances.append(z_center - cls)
                d_min_zone = min(zone_distances, key=abs)
                dist_zone_nearest[i] = (d_min_zone / cls) * 100

    df["n_single_prints_pct"] = n_sp_pct
    df["dist_single_print_nearest_pct"] = dist_nearest.astype("float32")
    df["has_single_print_above"] = has_above
    # ZONE features
    df["n_single_print_zones"] = n_zones
    # FIX 28/04 v4 : max_zone_width raw (ticks) en helper, version ATR ML-usable
    df["max_single_print_zone_width_ticks"] = max_zone_width_ticks  # helper raw
    if "atr" in df.columns:
        atr_safe = df["atr"].replace(0, np.nan)
        df["max_single_print_zone_width_atr"] = (max_zone_width_ticks / atr_safe).astype("float32")
    else:
        df["max_single_print_zone_width_atr"] = np.nan
    df["dist_single_print_zone_nearest_pct"] = dist_zone_nearest.astype("float32")
    return df


# ═══════════════════════════════════════════════════════════════════════════════
# Bloc 4 : Excess (vrai tail)
# ═══════════════════════════════════════════════════════════════════════════════

EXCESS_HIGH_TOLERANCE_TICKS = 1  # tolerance touch high/low (1 tick = pixel-perfect)
EXCESS_MAX_BARS_AT_EXTREME = 2   # <= 2 bars qui touchent EXACTEMENT le high = rejet rapide


def add_excess_features(
    df: pd.DataFrame,
    tick: float = DEFAULT_TICK_SIZE,
) -> pd.DataFrame:
    """
    Detecte les excess (tail) sur la session precedente.

    FIX 28/04 v2 (quality-auditor) : approche Dalton STRICTE.
    Excess = high de session touche EXACTEMENT (au tick pres) <= 2 fois sur la
    session = rejet brutal sans acceptance.

    Algorithme V4 :
      1. Pour chaque session, sess_high = max(high), sess_low = min(low)
      2. Count bars dont high >= sess_high - 1 tick (= pixel-perfect au tick pres)
      3. Excess high = count entre 1 et 2 (rejet rapide brutal)
      4. Idem pour excess low

    Features generees (4) :
      - is_excess_high_prev (boolean)
      - is_excess_low_prev (boolean)
      - dist_excess_high_pct (distance prev sess high si excess)
      - dist_excess_low_pct (distance prev sess low si excess)

    Convention : "_prev" = la feature represente le statut de la session J-1
    broadcast sur la session J. Donc pas de lookahead.
    """
    df = df.copy()
    required = ["session_date_trading", "high", "low", "close"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise KeyError(f"[Phase D Excess] manquant : {missing}")

    sess_dates = sorted(df["session_date_trading"].unique())

    # Pour chaque session, calculer is_excess_high/low + level
    excess_per_session = {}  # sess_date -> (is_high, is_low, high_level, low_level)
    tolerance = EXCESS_HIGH_TOLERANCE_TICKS * tick

    for sess_date, sess_grp in df.groupby("session_date_trading"):
        if sess_grp.empty:
            continue
        sess_high = sess_grp["high"].max()
        sess_low = sess_grp["low"].min()
        if pd.isna(sess_high) or pd.isna(sess_low):
            continue

        # FIX 28/04 v2 : count bars qui touchent EXACTEMENT le high (au tick pres)
        # high >= sess_high - 1 tick (= au tick du high)
        n_bars_at_high = ((sess_grp["high"] >= sess_high - tolerance)).sum()
        n_bars_at_low = ((sess_grp["low"] <= sess_low + tolerance)).sum()

        # Excess Dalton = rejet rapide = 1 ou 2 bars seulement touchent l'extreme
        is_excess_high = bool(1 <= n_bars_at_high <= EXCESS_MAX_BARS_AT_EXTREME)
        is_excess_low = bool(1 <= n_bars_at_low <= EXCESS_MAX_BARS_AT_EXTREME)
        excess_per_session[sess_date] = (is_excess_high, is_excess_low, sess_high, sess_low)

    # Mapper session J -> excess de session J-1
    sess_to_prev_excess = {}
    for i, d in enumerate(sess_dates):
        if i > 0:
            sess_to_prev_excess[d] = excess_per_session.get(sess_dates[i - 1], (False, False, np.nan, np.nan))
        else:
            sess_to_prev_excess[d] = (False, False, np.nan, np.nan)

    # Mapper sur df
    n = len(df)
    is_eh = np.zeros(n, dtype=np.int8)
    is_el = np.zeros(n, dtype=np.int8)
    dist_eh = np.full(n, np.nan, dtype=np.float64)
    dist_el = np.full(n, np.nan, dtype=np.float64)

    close_arr = df["close"].values
    sess_arr = df["session_date_trading"].values

    for i in range(n):
        sess = sess_arr[i]
        eh, el, h_lvl, l_lvl = sess_to_prev_excess.get(sess, (False, False, np.nan, np.nan))
        is_eh[i] = int(eh)
        is_el[i] = int(el)
        if eh and not np.isnan(h_lvl) and close_arr[i] > 0:
            dist_eh[i] = (close_arr[i] - h_lvl) / close_arr[i] * 100
        if el and not np.isnan(l_lvl) and close_arr[i] > 0:
            dist_el[i] = (close_arr[i] - l_lvl) / close_arr[i] * 100

    df["is_excess_high_prev"] = is_eh
    df["is_excess_low_prev"] = is_el
    df["dist_excess_high_pct"] = dist_eh.astype("float32")
    df["dist_excess_low_pct"] = dist_el.astype("float32")
    return df


# ═══════════════════════════════════════════════════════════════════════════════
# Pipeline complet
# ═══════════════════════════════════════════════════════════════════════════════

PHASE_D_GENERATED = {
    # pVWAP (3 helpers + 3 ML)
    "pvwap", "pvwap_sd1u", "pvwap_sd1d",
    "dist_pvwap_pct", "dist_pvwap_sd1u_pct", "dist_pvwap_sd1d_pct",
    # Naked POC (4 ML)
    "n_naked_poc_active", "dist_naked_poc_nearest_pct",
    "naked_poc_age_max_days", "n_naked_poc_within_0_5pct",
    # Single Prints (6 ML) - FIX 28/04 v4 ajout vue ZONE
    "n_single_prints_pct", "dist_single_print_nearest_pct",
    "has_single_print_above",
    # ZONE features (regroupe single prints contigus = mouvement impulsif Dalton)
    "n_single_print_zones", "max_single_print_zone_width_ticks",
    "max_single_print_zone_width_atr",  # FIX 28/04 v4 ATR-normalise (ML)
    "dist_single_print_zone_nearest_pct",
    # Legacy a dropper (residu d'ancien nom, FIX 28/04 v3)
    "n_single_prints_session",
    # Legacy excess dropped 28/04 v3 (a dropper si parquet le contient deja)
    "is_excess_high_prev", "is_excess_low_prev",
    "dist_excess_high_pct", "dist_excess_low_pct",
    # Excess DROPPED 28/04 v3 (incompatible 1m bars)
    # Sur sessions 24h x 1380 bars 1m, le high session est touche <= 2 bars
    # quasi-systematiquement (94.8% NQ, 77.7% ES) -> feature saturee.
    # Le concept Dalton est calibre 30m bars (1 TPO = 30 min). V4 utilise 1m
    # bars donc le concept "rejet en <= 2 TPO" devient toujours True.
    # A reimplementer Phase E avec approche Volume Profile based (volume
    # touche au high < seuil percentile) au lieu de count-based.
}

PHASE_D_HELPERS = {"pvwap", "pvwap_sd1u", "pvwap_sd1d"}  # prix absolus (drop ML)


def apply_phase_d_dalton_levels(
    df: pd.DataFrame,
    trades_df: Optional[pd.DataFrame] = None,
    tick: float = DEFAULT_TICK_SIZE,
) -> pd.DataFrame:
    """
    Pipeline complet Phase D : pVWAP + Naked POC + Single Prints + Excess.
    Idempotent : drop existing avant recalcul.
    """
    df = df.copy()
    drop_existing = [c for c in PHASE_D_GENERATED if c in df.columns]
    if drop_existing:
        df = df.drop(columns=drop_existing)

    df = add_pvwap_features(df)
    df = add_naked_poc_features(df, tick=tick)
    df = add_single_prints_features(df, trades_df=trades_df, tick=tick)
    # DROPPED 28/04 v3 : add_excess_features (incompatible 1m bars, saturation)
    return df
