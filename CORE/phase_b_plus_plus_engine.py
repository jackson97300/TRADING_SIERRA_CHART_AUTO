"""
phase_b_plus_plus_engine.py — Phase B+++ MVP : features depuis Trades agreges.

Approche pragmatique : au lieu de reconstruire le footprint cellule complet
(slow ~30s/mois en Python pur), on agrege les Trades par bar pour extraire :
  - Big orders : count trades par tier de taille (>= seuil)
  - Cluster volume : count trades concentre sur 1 prix
  - Aggressor distribution : ratio buy_aggressor vs sell_aggressor
  - Trade size stats : max, p99, mean per bar
  - Trade arrival : trades/seconde (intensite)

Pour vrai footprint cellule (Edge Zones, Imbalance Diag exact, Double/Triple Ask),
voir Phase B++++ (post audit GO).

Inputs requis :
  - DataFrame v4_enriched (deja avec ts_event)
  - Trades parquet (price, size, side, ts_event)

Outputs : ~25 nouvelles features.

Auteur : Phase B+++ Session 1 (2026-04-26)
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from extension_lines_manager import ExtensionLineBuffer

TICK_SIZE = 0.25  # default ES/NQ. MGC=0.10 — caller passe tick=get_tick_size(symbol)

# Seuils par symbole (cf DMP_Config 3.7.13)
BIG_ORDER_TIERS = {
    "ES": [100, 150, 400, 1000],
    "NQ": [10, 30, 100, 300],
}
CLUSTER_THRESHOLDS = {
    "ES": 250,
    "NQ": 20,
}


# ═══════════════════════════════════════════════════════════════════════════════
# A. AGGREGATION TRADES PAR BAR (helper commun)
# ═══════════════════════════════════════════════════════════════════════════════

def aggregate_trades_per_bar(trades_df: pd.DataFrame, bar_starts: pd.Series,
                              tier_thresholds: list[int],
                              cluster_threshold: int,
                              bar_close: pd.Series = None,
                              tick: float = TICK_SIZE) -> pd.DataFrame:
    """
    Pour chaque bar [bar_starts[i], bar_starts[i+1]), agrege les trades :
      - n_big_t1, n_big_t2, n_big_t3, n_big_t4 (count trades size >= tier)
      - n_big_buy_t1..t4, n_big_sell_t1..t4 (split par aggressor)
      - max_size_buy, max_size_sell
      - n_clusters (count price levels avec sum(size) > cluster_threshold)
      - max_cluster_volume
      - aggressor_imbalance = (buy_count - sell_count) / (buy + sell)
      - p99_trade_size
      - max_delta_bar, min_delta_bar (cumul delta intra-bar)
      - n_ticks_bar (n distinct prices traded)
      - dist_big_ask/bid_nearest_pct, dist_cluster_nearest_up/dn_pct (si bar_close fourni)

    Returns DataFrame indexe par bar_idx.
    """
    if trades_df.empty:
        return pd.DataFrame()

    trades_df = trades_df.copy()
    trades_df["price_bucket"] = (trades_df["price"] / tick).round() * tick

    # Bar bins
    bar_starts = pd.Series(bar_starts).reset_index(drop=True)
    bar_ends = bar_starts.shift(-1).fillna(bar_starts.iloc[-1] + pd.Timedelta("1min"))

    # Bin trades to bar idx
    trades_sorted = trades_df.sort_values("ts_event").reset_index(drop=True)
    bar_idx = np.searchsorted(bar_starts.values, trades_sorted["ts_event"].values, side="right") - 1
    bar_idx = np.clip(bar_idx, 0, len(bar_starts) - 1)
    trades_sorted["bar_idx"] = bar_idx

    # Filter trades hors bars (timestamps avant 1ere bar)
    trades_sorted = trades_sorted[trades_sorted["ts_event"] >= bar_starts.iloc[0]]
    if trades_sorted.empty:
        return pd.DataFrame()

    # Aggregations par bar
    grouped = trades_sorted.groupby("bar_idx", sort=False)

    # Big orders by tier (total + buy + sell)
    out = {}
    for i, thresh in enumerate(tier_thresholds, start=1):
        mask = trades_sorted["size"] >= thresh
        sub = trades_sorted[mask]
        out[f"n_big_t{i}"] = sub.groupby("bar_idx").size().reindex(grouped.size().index, fill_value=0)
        out[f"n_big_buy_t{i}"] = sub[sub["side"] == "A"].groupby("bar_idx").size().reindex(grouped.size().index, fill_value=0)
        out[f"n_big_sell_t{i}"] = sub[sub["side"] == "B"].groupby("bar_idx").size().reindex(grouped.size().index, fill_value=0)

    # Max size per bar (split buy/sell)
    out["max_size_buy"] = trades_sorted[trades_sorted["side"] == "A"].groupby("bar_idx")["size"].max().reindex(grouped.size().index, fill_value=0)
    out["max_size_sell"] = trades_sorted[trades_sorted["side"] == "B"].groupby("bar_idx")["size"].max().reindex(grouped.size().index, fill_value=0)
    out["p99_trade_size"] = grouped["size"].quantile(0.99)

    # Aggressor imbalance — FIX 3 : exclure side='N' (auctions/halts) du denominateur
    n_buy = trades_sorted[trades_sorted["side"] == "A"].groupby("bar_idx").size().reindex(grouped.size().index, fill_value=0)
    n_sell = trades_sorted[trades_sorted["side"] == "B"].groupby("bar_idx").size().reindex(grouped.size().index, fill_value=0)
    n_directional = n_buy + n_sell  # exclut side='N'
    out["aggressor_imbalance"] = ((n_buy - n_sell) / n_directional.replace(0, np.nan)).fillna(0)

    # Volume clusters (price levels avec sum(size) > cluster_threshold)
    cluster_df = trades_sorted.groupby(["bar_idx", "price_bucket"])["size"].sum().reset_index()
    cluster_count = (cluster_df[cluster_df["size"] >= cluster_threshold]
                     .groupby("bar_idx").size()
                     .reindex(grouped.size().index, fill_value=0))
    out["n_clusters"] = cluster_count
    out["max_cluster_volume"] = cluster_df.groupby("bar_idx")["size"].max().reindex(grouped.size().index, fill_value=0)

    # FPBS subgraphs intra-bar (NOUVEAU - D.1)
    # max_delta_bar / min_delta_bar : cumul signe size DANS la barre (reset par groupe)
    # FIX uint64 overflow : caster size en int64 AVANT negation (-uint64 -> overflow)
    size_int = trades_sorted["size"].astype("int64")
    trades_sorted["signed_size"] = np.where(
        trades_sorted["side"] == "A", size_int,
        np.where(trades_sorted["side"] == "B", -size_int, 0)
    ).astype("int64")
    cumdelta_per_bar = trades_sorted.groupby("bar_idx")["signed_size"].cumsum()
    trades_sorted["cumdelta_bar"] = cumdelta_per_bar.astype("int64")
    out["max_delta_bar"] = trades_sorted.groupby("bar_idx")["cumdelta_bar"].max().reindex(grouped.size().index, fill_value=0).astype("int64")
    out["min_delta_bar"] = trades_sorted.groupby("bar_idx")["cumdelta_bar"].min().reindex(grouped.size().index, fill_value=0).astype("int64")
    out["n_ticks_bar"] = (trades_sorted.groupby("bar_idx")["price_bucket"].nunique()
                          .reindex(grouped.size().index, fill_value=0))

    # Distances big ASK/BID + cluster nearest pct (NOUVEAU - B.1/B.2 complet)
    if bar_close is not None:
        # Big ASK nearest = prix de cell ask >= seuil tier1, le plus proche du close
        big_ask_prices = trades_sorted[
            (trades_sorted["side"] == "A") & (trades_sorted["size"] >= tier_thresholds[0])
        ].groupby("bar_idx")["price_bucket"].apply(list)
        big_bid_prices = trades_sorted[
            (trades_sorted["side"] == "B") & (trades_sorted["size"] >= tier_thresholds[0])
        ].groupby("bar_idx")["price_bucket"].apply(list)
        cluster_prices_per_bar = (cluster_df[cluster_df["size"] >= cluster_threshold]
                                   .groupby("bar_idx")["price_bucket"].apply(list))

        bar_close_idx = bar_close.reset_index(drop=True)
        dist_big_ask = []
        dist_big_bid = []
        dist_cluster_up = []
        dist_cluster_dn = []
        for bidx in grouped.size().index:
            cls = bar_close_idx.iloc[bidx] if bidx < len(bar_close_idx) else np.nan
            if pd.isna(cls):
                dist_big_ask.append(np.nan)
                dist_big_bid.append(np.nan)
                dist_cluster_up.append(np.nan)
                dist_cluster_dn.append(np.nan)
                continue
            ba = big_ask_prices.get(bidx, [])
            bb = big_bid_prices.get(bidx, [])
            cl = cluster_prices_per_bar.get(bidx, [])
            dist_big_ask.append(min((abs(p - cls) for p in ba), default=np.nan) / cls * 100 if ba else np.nan)
            dist_big_bid.append(min((abs(p - cls) for p in bb), default=np.nan) / cls * 100 if bb else np.nan)
            ups = [p for p in cl if p > cls]
            dns = [p for p in cl if p < cls]
            dist_cluster_up.append((min(ups) - cls) / cls * 100 if ups else np.nan)
            dist_cluster_dn.append((cls - max(dns)) / cls * 100 if dns else np.nan)
        out["dist_big_ask_nearest_pct"] = pd.Series(dist_big_ask, index=grouped.size().index)
        out["dist_big_bid_nearest_pct"] = pd.Series(dist_big_bid, index=grouped.size().index)
        out["dist_cluster_nearest_up_pct"] = pd.Series(dist_cluster_up, index=grouped.size().index)
        out["dist_cluster_nearest_dn_pct"] = pd.Series(dist_cluster_dn, index=grouped.size().index)

    return pd.DataFrame(out)


# ═══════════════════════════════════════════════════════════════════════════════
# B. APPLY PHASE B+++ FEATURES
# ═══════════════════════════════════════════════════════════════════════════════

# BN #6 Absorption Ask/Bid (Chart 1 ES ID 25/26 + Chart 2 NQ ID 29/30)
# 06/05 calibration NQ : audit market-analyst empirique post-fix +/-1 tick.
# Sur ES seuil 10/20 fonctionne. Sur NQ avec 20 BID, 4 features post-fix encore
# DEAD (bn_trapped_*_at_*, bn_absorb_bid_at_level) = NQ moins liquide
# qu'ES (ratio depth ~0.4). Justification reco market-analyst : 20 * 0.4 = 8.
# Dry-run : si fire rate >5% post-rebuild => seuil trop bas, remonter a 12.
ABSORPTION_THRESHOLD_ASK_BY_SYM = {"ES": 10, "NQ": 4}   # ratio 0.4 (NQ 10 -> 4)
ABSORPTION_THRESHOLD_BID_BY_SYM = {"ES": 20, "NQ": 8}   # ratio 0.4 (NQ 20 -> 8)
# Backward-compat aliases (default ES values, used si symbol="UNKNOWN")
ABSORPTION_THRESHOLD_ASK = 10
ABSORPTION_THRESHOLD_BID = 20
ABSORPTION_RATIO = 3
ABSORPTION_PROXIMITY_TICKS = {"ES": 5, "NQ": 10}

# Niveaux RESISTANCE pour bn_absorb_ask_at_level
ABSORPTION_RESISTANCE_LEVELS = [
    "mq_call_resistance", "mq_call_resistance_0dte",
    "prev_vah", "pdh", "cur_vah", "cur_pdh",
    "sess_high", "ib_high", "mq_1d_max",
    "vwap_d_sd1u", "vwap_d_sd2u", "vwap_d_sd3u",
]
# Niveaux SUPPORT pour bn_absorb_bid_at_level
ABSORPTION_SUPPORT_LEVELS = [
    "mq_put_support", "mq_put_support_0dte",
    "prev_val", "pdl", "cur_val", "cur_pdl",
    "sess_low", "ib_low", "mq_1d_min",
    "vwap_d_sd1d", "vwap_d_sd2d", "vwap_d_sd3d",
]


# BN #7 Double Ask/Bid ES (Chart 1 ID 27/28) + Triple Ask/Bid NQ (Chart 2 ID 27/28)
STACK_N_CELLS = {"ES": 2, "NQ": 3}  # ES = Double (2 cellules), NQ = Triple (3 cellules)

# BN #8 Big Orders multi-tier (Volume At Price Threshold Alert V2)
# Pas de formule alert : etude scan cellules VAP, marker si AskVol/BidVol >= seuil
BIG_ORDERS_TIERS_NEW = {
    # FIX 27/04 (audit ULTRATHINK + market-analyst rescue) :
    # Tier 3 (ES=400, NQ=100) stuck 1939 bars empirique = events trop rares.
    # DROP tier 3 cote ES + NQ. Garder t1/t2 avec NQ recalibre.
    # NQ avant : [10, 30] -> fire ratio NQ/ES = 3.30 (fuite instrument).
    # NQ apres : [40, 80] (cible fire ratio NQ/ES < 1.5).
    "ES": [100, 150, None, None],  # 2 tiers actifs (t3/t4 dropped audit 27/04)
    "NQ": [40, 80, None, None],    # AVANT [10, 30, 100, None]
}

# BN #9 CLUSTER VOLUME (Volume At Price Threshold Alert V2 - Total Volume)
# FIX 27/04 : NQ avant=20 (ratio fuite 2.62-2.77) -> apres=70 (ratio cible <1.5).
CLUSTER_VOLUME_THRESHOLD = {
    "ES": 250,   # Chart 1 ID 10
    "NQ": 70,    # AVANT 20 (audit 27/04 : ratio fuite NQ/ES x2.77)
}
CLUSTER_VOLUME_MIN_GROUP = 2  # ES + NQ both


def add_big_orders_features_v2(df, footprint, symbol="ES", tick=TICK_SIZE):
    """
    BN #8 Big Orders multi-tier (Volume At Price Threshold Alert V2).

    Pas de formule alert : pour chaque bar, scan TOUTES les cellules VAP.
    Si AskVolume(cellule) >= seuil_tier -> marker (cellule "big ask order").
    Idem pour BidVolume.

    Tiers per-symbole :
      ES : 100, 150, 400, 1000 (Chart 1 ID 102/103, 6/7, 8/9, 29/30)
      NQ : 10, 30, 100 (Chart 2 ID 8/9, 10/11, 31/32) - pas de t4

    Output : pour chaque tier T,
      n_big_ask_tT : count cellules dans la bar avec AskVol >= seuil_T
      n_big_bid_tT : count cellules dans la bar avec BidVol >= seuil_T
      max_big_ask_vol_in_bar : max AskVol sur toutes cellules
      max_big_bid_vol_in_bar : max BidVol

    Tier 4 NQ : NaN/0 (pas d'etude SC NQ)
    """
    df = df.copy()
    sym = symbol.upper().split(".")[0]
    tiers = BIG_ORDERS_TIERS_NEW.get(sym, BIG_ORDERS_TIERS_NEW["ES"])

    n = len(df)
    n_ask_t = {f"t{i+1}": np.zeros(n, dtype=np.int32) for i in range(4)}
    n_bid_t = {f"t{i+1}": np.zeros(n, dtype=np.int32) for i in range(4)}
    max_ask = np.zeros(n, dtype=np.int32)
    max_bid = np.zeros(n, dtype=np.int32)

    for i in range(n):
        cells = footprint.get(i, {})
        if not cells:
            continue
        bar_max_ask = 0
        bar_max_bid = 0
        for cell in cells.values():
            ask_v = cell.get("ask_vol", 0)
            bid_v = cell.get("bid_vol", 0)
            if ask_v > bar_max_ask: bar_max_ask = ask_v
            if bid_v > bar_max_bid: bar_max_bid = bid_v
            for ti, seuil in enumerate(tiers):
                if seuil is None:
                    continue
                if ask_v >= seuil:
                    n_ask_t[f"t{ti+1}"][i] += 1
                if bid_v >= seuil:
                    n_bid_t[f"t{ti+1}"][i] += 1
        max_ask[i] = bar_max_ask
        max_bid[i] = bar_max_bid

    for ti in range(4):
        col_a = f"n_big_ask_v2_t{ti+1}"
        col_b = f"n_big_bid_v2_t{ti+1}"
        if tiers[ti] is None:
            df[col_a] = 0
            df[col_b] = 0
        else:
            df[col_a] = n_ask_t[f"t{ti+1}"]
            df[col_b] = n_bid_t[f"t{ti+1}"]
    df["max_big_ask_vol_in_bar"] = max_ask
    df["max_big_bid_vol_in_bar"] = max_bid
    return df


def add_stack_features(df, footprint, symbol="ES", tick=TICK_SIZE):
    """
    BN #7 Double ES (ID 27/28 Chart 1) + Triple NQ (ID 27/28 Chart 2).

    SC formules officielles Jackson 27/04 :

    ES DOUBLE ASK = AND(O>C[-1],
                          AVAP(H,0)>=1, BVAP(H,0)=0,
                          AVAP(H-TICKSIZE,0)>=1, BVAP(H-TICKSIZE,0)=0)
    ES DOUBLE BID = AND(O<C[-1],
                          AVAP(L,0)=0, BVAP(L,0)>=1,
                          AVAP(L+TICKSIZE,0)=0, BVAP(L+TICKSIZE,0)>=1)

    NQ TRIPLE ASK = idem ES + 3eme cellule (H-TICKSIZE*2)
    NQ TRIPLE BID = idem ES + 3eme cellule (L+TICKSIZE*2)

    Logique : STACK PUR ASK ou BID au top/bottom de la barre = aucun trade
    de l'autre cote sur N cellules consecutives = signal "iceberg" institutionnel.

    2 features generees (nom uniforme per-symbole) :
      bn_stack_ask : 2 cellules ES / 3 cellules NQ (Double / Triple)
      bn_stack_bid : idem

    Compatibilite : noms uniformes pour permettre concat ES + NQ datasets.
    """
    df = df.copy()
    sym = symbol.upper().split(".")[0]
    n_cells = STACK_N_CELLS.get(sym, 2)

    n = len(df)
    stack_ask = np.zeros(n, dtype=np.int8)
    stack_bid = np.zeros(n, dtype=np.int8)

    high_arr = df["high"].values
    low_arr = df["low"].values
    open_arr = df["open"].values
    close_arr = df["close"].values

    for i in range(n):
        if i == 0:
            continue
        c_prev = close_arr[i-1]
        bar_high = high_arr[i]
        bar_low = low_arr[i]
        bar_open = open_arr[i]
        cells = footprint.get(i, {})
        if not cells:
            continue

        # STACK ASK : O>C[-1] AND N cellules pures ASK consecutives au TOP (H, H-1, H-2...)
        if bar_open > c_prev:
            stack_ask_ok = True
            for k in range(n_cells):
                p = round((bar_high - tick * k) / tick) * tick
                cell = cells.get(p)
                if cell is None:
                    stack_ask_ok = False
                    break
                ask_v = cell.get("ask_vol", 0)
                bid_v = cell.get("bid_vol", 0)
                if not (ask_v >= 1 and bid_v == 0):
                    stack_ask_ok = False
                    break
            if stack_ask_ok:
                stack_ask[i] = 1

        # STACK BID : O<C[-1] AND N cellules pures BID consecutives au BOT (L, L+1, L+2...)
        if bar_open < c_prev:
            stack_bid_ok = True
            for k in range(n_cells):
                p = round((bar_low + tick * k) / tick) * tick
                cell = cells.get(p)
                if cell is None:
                    stack_bid_ok = False
                    break
                ask_v = cell.get("ask_vol", 0)
                bid_v = cell.get("bid_vol", 0)
                if not (ask_v == 0 and bid_v >= 1):
                    stack_bid_ok = False
                    break
            if stack_bid_ok:
                stack_bid[i] = 1

    df["bn_stack_ask"] = stack_ask
    df["bn_stack_bid"] = stack_bid
    return df


def add_delta_div_extension_lines(df: pd.DataFrame, cluster_pct: float = 0.2) -> pd.DataFrame:
    """
    BN #12 Delta Divergence Extension Lines (Chart 26 ES ID 31/32 + Chart 27 NQ).
    Reproduit `Draw Extension Lines at Color Bar Value = Extend to Future Inters`.

    delta_div_buy fire bar i  -> zone SUPPORT au LOW de la bar (institutional buyers)
    delta_div_sell fire bar i -> zone RESISTANCE au HIGH de la bar (institutional sellers)

    Zone reste active jusqu'a touche prix futur (overlap bar.low <= zone.price <= bar.high).
    Logique Jackson : zones non-touchees groupees pres du prix = niveau puissant.

    6 features generees :
      n_delta_div_buy_zones_active, n_delta_div_sell_zones_active
      dist_delta_div_buy_nearest_pct, dist_delta_div_sell_nearest_pct
      n_delta_div_buy_cluster_within_0_2pct, n_delta_div_sell_cluster_within_0_2pct
    """
    df = df.copy()
    n = len(df)
    buf_buy = ExtensionLineBuffer()
    buf_sell = ExtensionLineBuffer()

    n_buy_active = np.zeros(n, dtype=np.int32)
    n_sell_active = np.zeros(n, dtype=np.int32)
    dist_buy = np.full(n, np.nan, dtype=np.float64)
    dist_sell = np.full(n, np.nan, dtype=np.float64)
    n_buy_cluster = np.zeros(n, dtype=np.int32)
    n_sell_cluster = np.zeros(n, dtype=np.int32)

    high_arr = df["high"].values
    low_arr = df["low"].values
    close_arr = df["close"].values
    fire_buy = df["delta_div_buy"].values
    fire_sell = df["delta_div_sell"].values

    for i in range(n):
        bar_high = high_arr[i]
        bar_low = low_arr[i]
        close = close_arr[i]

        # 1. UPDATE buffers : deactivate zones touchees par ce bar
        buf_buy.update_with_bar(i, bar_low, bar_high)
        buf_sell.update_with_bar(i, bar_low, bar_high)

        # 2. ADD nouvelle zone si fire ce bar
        # delta_div_buy : zone SUPPORT au LOW (institutional buyers absorption)
        if fire_buy[i] == 1:
            buf_buy.add_zone(i, [float(bar_low)], "buy")
        # delta_div_sell : zone RESISTANCE au HIGH (institutional sellers absorption)
        if fire_sell[i] == 1:
            buf_sell.add_zone(i, [float(bar_high)], "sell")

        # 3. FEATURES count + nearest + cluster
        n_buy_active[i] = buf_buy.count_active("buy")
        n_sell_active[i] = buf_sell.count_active("sell")

        d_buy = buf_buy.nearest_distance("buy", close)
        d_sell = buf_sell.nearest_distance("sell", close)
        if not np.isnan(d_buy) and close > 0:
            dist_buy[i] = (d_buy / close) * 100
        if not np.isnan(d_sell) and close > 0:
            dist_sell[i] = (d_sell / close) * 100

        # Cluster : count zones actives dans [close-pct, close+pct]
        cluster_range = close * (cluster_pct / 100)
        cluster_low = close - cluster_range
        cluster_high = close + cluster_range
        n_buy_cluster[i] = sum(
            1 for z in buf_buy.zones
            if z.active and cluster_low <= z.min_price <= cluster_high
        )
        n_sell_cluster[i] = sum(
            1 for z in buf_sell.zones
            if z.active and cluster_low <= z.min_price <= cluster_high
        )

    df["n_delta_div_buy_zones_active"] = n_buy_active
    df["n_delta_div_sell_zones_active"] = n_sell_active
    df["dist_delta_div_buy_nearest_pct"] = dist_buy
    df["dist_delta_div_sell_nearest_pct"] = dist_sell
    df["n_delta_div_buy_cluster_within_0_2pct"] = n_buy_cluster
    df["n_delta_div_sell_cluster_within_0_2pct"] = n_sell_cluster
    return df


def _DEPRECATED_add_long_color_extension_lines(df: pd.DataFrame, cluster_pct: float = 0.2) -> pd.DataFrame:
    """DEPRECATED 06/05/2026 — remplacee par phase_b_plus_engine.add_long_extension_lines
    + add_color_extension_lines (dans Phase B+, sources `long_up_bar`/`long_dn_bar` +
    `bn_color_*_fwd1` reproduits en pur Python). Cette fonction cherchait `bar_long_*`/
    `bn_color_*` (DMP raw, pulse 1-bar) qui n'existent pas en V4 enriched mode mq-lite.
    Voir CLAUDE.md / DOCS/INCIDENT_LOG.md pour le contexte."""
    return df


def _UNUSED_add_long_color_extension_lines_legacy(df: pd.DataFrame, cluster_pct: float = 0.2) -> pd.DataFrame:
    """
    Fix Jackson 06/05 : LONG_UP/DN_BAR + COLOR_UP/DN doivent etre Extension Lines
    (zone reste active jusqu'a touche prix), pas pulse 1 barre.

    Bug racine : DMP_Reader.h ligne 1813 lit `DMP_ReadBN_Trigger(sg0)` = pulse
    1 barre = capture seulement la creation, pas le cycle de vie complet.
    Meme bug racine que delta_divergence (fix 07/04). Ces features sont
    des Extension Lines en Sierra Chart visuel ("AddLineUntilFutureIntersection")
    mais le DMP capture seulement le trigger initial.

    Solution : reutiliser le trigger DMP comme creation event + maintenir
    les zones cote Python avec ExtensionLineBuffer (pattern eprouve sur
    delta_div_buy/sell, edge_buy/sell, trapped_buyers/sellers).

    Conventions :
      bar_long_up_bar fire -> zone SUPPORT au LOW (continuation haussière, edge zone vert)
      bar_long_dn_bar fire -> zone RESISTANCE au HIGH (continuation baissière, edge zone rouge)
      bn_color_up fire     -> zone SUPPORT au LOW (cellule bullish, demande institutionnelle)
      bn_color_dn fire     -> zone RESISTANCE au HIGH (cellule bearish, offre institutionnelle)

    Features generees (12 features = 4 patterns x 3 metriques) :
      n_long_up_zones_active, n_long_dn_zones_active,
      n_color_up_zones_active, n_color_dn_zones_active,
      dist_long_up_nearest_pct, dist_long_dn_nearest_pct,
      dist_color_up_nearest_pct, dist_color_dn_nearest_pct,
      n_long_up_cluster_within_0_2pct, n_long_dn_cluster_within_0_2pct,
      n_color_up_cluster_within_0_2pct, n_color_dn_cluster_within_0_2pct
    """
    df = df.copy()
    n = len(df)

    # 4 buffers (un par pattern direction)
    buf_long_up = ExtensionLineBuffer()
    buf_long_dn = ExtensionLineBuffer()
    buf_color_up = ExtensionLineBuffer()
    buf_color_dn = ExtensionLineBuffer()

    # Output arrays
    n_lu_active = np.zeros(n, dtype=np.int32)
    n_ld_active = np.zeros(n, dtype=np.int32)
    n_cu_active = np.zeros(n, dtype=np.int32)
    n_cd_active = np.zeros(n, dtype=np.int32)
    dist_lu = np.full(n, np.nan, dtype=np.float64)
    dist_ld = np.full(n, np.nan, dtype=np.float64)
    dist_cu = np.full(n, np.nan, dtype=np.float64)
    dist_cd = np.full(n, np.nan, dtype=np.float64)
    n_lu_cluster = np.zeros(n, dtype=np.int32)
    n_ld_cluster = np.zeros(n, dtype=np.int32)
    n_cu_cluster = np.zeros(n, dtype=np.int32)
    n_cd_cluster = np.zeros(n, dtype=np.int32)

    high_arr = df["high"].values
    low_arr = df["low"].values
    close_arr = df["close"].values
    # Triggers (peuvent etre absents du DMP — fallback 0)
    fire_lu = df["bar_long_up_bar"].values if "bar_long_up_bar" in df.columns else np.zeros(n)
    fire_ld = df["bar_long_dn_bar"].values if "bar_long_dn_bar" in df.columns else np.zeros(n)
    fire_cu = df["bn_color_up"].values if "bn_color_up" in df.columns else np.zeros(n)
    fire_cd = df["bn_color_dn"].values if "bn_color_dn" in df.columns else np.zeros(n)

    for i in range(n):
        bar_high = high_arr[i]
        bar_low = low_arr[i]
        close = close_arr[i]

        # 1. UPDATE buffers : deactivate zones touchees par cette bar
        buf_long_up.update_with_bar(i, bar_low, bar_high)
        buf_long_dn.update_with_bar(i, bar_low, bar_high)
        buf_color_up.update_with_bar(i, bar_low, bar_high)
        buf_color_dn.update_with_bar(i, bar_low, bar_high)

        # 2. ADD nouvelles zones si fire (NaN-safe)
        if fire_lu[i] == 1: buf_long_up.add_zone(i, [float(bar_low)], "buy")
        if fire_ld[i] == 1: buf_long_dn.add_zone(i, [float(bar_high)], "sell")
        if fire_cu[i] == 1: buf_color_up.add_zone(i, [float(bar_low)], "buy")
        if fire_cd[i] == 1: buf_color_dn.add_zone(i, [float(bar_high)], "sell")

        # 3. FEATURES count + nearest distance
        n_lu_active[i] = buf_long_up.count_active("buy")
        n_ld_active[i] = buf_long_dn.count_active("sell")
        n_cu_active[i] = buf_color_up.count_active("buy")
        n_cd_active[i] = buf_color_dn.count_active("sell")

        if close > 0:
            d_lu = buf_long_up.nearest_distance("buy", close)
            d_ld = buf_long_dn.nearest_distance("sell", close)
            d_cu = buf_color_up.nearest_distance("buy", close)
            d_cd = buf_color_dn.nearest_distance("sell", close)
            if not np.isnan(d_lu): dist_lu[i] = (d_lu / close) * 100
            if not np.isnan(d_ld): dist_ld[i] = (d_ld / close) * 100
            if not np.isnan(d_cu): dist_cu[i] = (d_cu / close) * 100
            if not np.isnan(d_cd): dist_cd[i] = (d_cd / close) * 100

        # Cluster (zones actives dans +/- cluster_pct du close)
        cluster_range = close * (cluster_pct / 100)
        cluster_low = close - cluster_range
        cluster_high = close + cluster_range
        n_lu_cluster[i] = sum(1 for z in buf_long_up.zones if z.active and cluster_low <= z.min_price <= cluster_high)
        n_ld_cluster[i] = sum(1 for z in buf_long_dn.zones if z.active and cluster_low <= z.min_price <= cluster_high)
        n_cu_cluster[i] = sum(1 for z in buf_color_up.zones if z.active and cluster_low <= z.min_price <= cluster_high)
        n_cd_cluster[i] = sum(1 for z in buf_color_dn.zones if z.active and cluster_low <= z.min_price <= cluster_high)

    df["n_long_up_zones_active"] = n_lu_active
    df["n_long_dn_zones_active"] = n_ld_active
    df["n_color_up_zones_active"] = n_cu_active
    df["n_color_dn_zones_active"] = n_cd_active
    df["dist_long_up_nearest_pct"] = dist_lu
    df["dist_long_dn_nearest_pct"] = dist_ld
    df["dist_color_up_nearest_pct"] = dist_cu
    df["dist_color_dn_nearest_pct"] = dist_cd
    df["n_long_up_cluster_within_0_2pct"] = n_lu_cluster
    df["n_long_dn_cluster_within_0_2pct"] = n_ld_cluster
    df["n_color_up_cluster_within_0_2pct"] = n_cu_cluster
    df["n_color_dn_cluster_within_0_2pct"] = n_cd_cluster
    return df


# BN bonus Trapped Traders (ICT/SMC + KISS Orderflow + TradePro)
TRAPPED_THRESHOLD_VOL = {"ES": 30, "NQ": 10}
TRAPPED_FINISH_PCT_BUYERS = 30  # close dans le bottom 30% du range bar
TRAPPED_FINISH_PCT_SELLERS = 70  # close dans le top 70% du range bar


def add_trapped_traders_features(df, footprint, symbol="ES", tick=TICK_SIZE,
                                   cluster_pct: float = 0.2):
    """
    BN bonus Trapped Traders (concept ICT/SMC pro).

    Trapped Buyers : aggressive buy au HIGH cellule, close pres du LOW
      -> buyers pieges long, devront liquider plus tard
      -> niveau HIGH = demande latente (resistance future)

    Trapped Sellers : aggressive sell au LOW cellule, close pres du HIGH
      -> sellers pieges short, short squeeze imminent
      -> niveau LOW = offer latent (support future)

    Formules (consolide pro standards) :
      Trapped Buyers = AND(
        AskVol(H) >= seuil,           # buyers aggresse au top
        finish_pct_up <= 30,           # close pres du LOW
        delta_bar > 0,                 # delta positif MAIS prix retombe
        close < open                   # bar baissiere
      )
      Trapped Sellers = miroir (BidVol(L) seuil + finish_pct_up>=70 + delta<0 + close>open)

    Seuils per-symbole : ES=30 / NQ=10 (ratio 3:1 coherent avec Big Orders).

    + Variant ICT : combine avec niveau cle (near_resistance/support).
    + Extension Lines : zones persistantes jusqu'a touche prix futur (= liquidation forcee).
    + Clusters : zones non-touchees groupees pres du prix = signal extra puissant.

    10 features generees :
      bn_trapped_buyers_raw, bn_trapped_sellers_raw
      bn_trapped_buyers_at_resistance, bn_trapped_sellers_at_support
      n_trapped_buyers_zones_active, n_trapped_sellers_zones_active
      dist_trapped_buyers_nearest_pct, dist_trapped_sellers_nearest_pct
      n_trapped_buyers_cluster_within_0_2pct, n_trapped_sellers_cluster_within_0_2pct
    """
    df = df.copy()
    sym = symbol.upper().split(".")[0]
    threshold = TRAPPED_THRESHOLD_VOL.get(sym, 10)

    n = len(df)
    trap_buy_raw = np.zeros(n, dtype=np.int8)
    trap_sell_raw = np.zeros(n, dtype=np.int8)

    high_arr = df["high"].values
    low_arr = df["low"].values
    open_arr = df["open"].values
    close_arr = df["close"].values
    delta_arr = df["delta_bar"].values if "delta_bar" in df.columns else np.zeros(n)

    # Niveaux pour at_resistance / at_support (reuse des cols deja calculees)
    has_near_res = "near_resistance_level" in df.columns
    has_near_sup = "near_support_level" in df.columns

    # Detection raw + Extension Lines
    buf_buy = ExtensionLineBuffer()
    buf_sell = ExtensionLineBuffer()

    n_buy_active = np.zeros(n, dtype=np.int32)
    n_sell_active = np.zeros(n, dtype=np.int32)
    dist_buy = np.full(n, np.nan, dtype=np.float64)
    dist_sell = np.full(n, np.nan, dtype=np.float64)
    n_buy_cluster = np.zeros(n, dtype=np.int32)
    n_sell_cluster = np.zeros(n, dtype=np.int32)

    for i in range(n):
        bar_high = high_arr[i]
        bar_low = low_arr[i]
        bar_open = open_arr[i]
        close = close_arr[i]
        delta = delta_arr[i]
        cells = footprint.get(i, {})

        # finish_pct_up : position close dans range bar (0=low, 100=high)
        bar_range = bar_high - bar_low
        if bar_range > 0:
            finish_pct = (close - bar_low) / bar_range * 100
        else:
            finish_pct = 50

        # 1. UPDATE buffers : deactivate zones touchees par ce bar
        buf_buy.update_with_bar(i, bar_low, bar_high)
        buf_sell.update_with_bar(i, bar_low, bar_high)

        # 2. DETECT trapped buyers
        # FIX 05/05/2026 : scan zone top [H, H-tick] au lieu de H exact.
        # Cause : NQ trapped_buyers_raw fire 0.027% (cell H rate quasi-systematiquement
        # car high souvent meche d'1 trade). Sum sur 2 cellules captera les vrais
        # gros AskVol au top du footprint.
        # Empirique attendu : NQ 0.027% -> 0.3-0.8%, ES 1.15% -> 2-3%.
        if cells:
            ask_h = 0.0
            for k in (0, 1):
                p = round((bar_high - tick * k) / tick) * tick
                cell_p = cells.get(p)
                if cell_p:
                    ask_h += cell_p.get("ask_vol", 0)
            if (ask_h >= threshold and finish_pct <= TRAPPED_FINISH_PCT_BUYERS
                    and delta > 0 and close < bar_open):
                trap_buy_raw[i] = 1
                buf_buy.add_zone(i, [float(bar_high)], "buy")

            # 3. DETECT trapped sellers
            bid_l = 0.0
            for k in (0, 1):
                p = round((bar_low + tick * k) / tick) * tick
                cell_p = cells.get(p)
                if cell_p:
                    bid_l += cell_p.get("bid_vol", 0)
            if (bid_l >= threshold and finish_pct >= TRAPPED_FINISH_PCT_SELLERS
                    and delta < 0 and close > bar_open):
                trap_sell_raw[i] = 1
                buf_sell.add_zone(i, [float(bar_low)], "sell")

        # 4. FEATURES count + nearest + cluster
        n_buy_active[i] = buf_buy.count_active("buy")
        n_sell_active[i] = buf_sell.count_active("sell")

        d_buy = buf_buy.nearest_distance("buy", close)
        d_sell = buf_sell.nearest_distance("sell", close)
        if not np.isnan(d_buy) and close > 0:
            dist_buy[i] = (d_buy / close) * 100
        if not np.isnan(d_sell) and close > 0:
            dist_sell[i] = (d_sell / close) * 100

        # Cluster
        cluster_range = close * (cluster_pct / 100)
        cluster_low = close - cluster_range
        cluster_high = close + cluster_range
        n_buy_cluster[i] = sum(
            1 for z in buf_buy.zones
            if z.active and cluster_low <= z.min_price <= cluster_high
        )
        n_sell_cluster[i] = sum(
            1 for z in buf_sell.zones
            if z.active and cluster_low <= z.min_price <= cluster_high
        )

    df["bn_trapped_buyers_raw"] = trap_buy_raw
    df["bn_trapped_sellers_raw"] = trap_sell_raw

    # at_resistance / at_support si cols disponibles
    if has_near_res:
        df["bn_trapped_buyers_at_resistance"] = (trap_buy_raw & df["near_resistance_level"].values).astype(np.int8)
    else:
        df["bn_trapped_buyers_at_resistance"] = 0
    if has_near_sup:
        df["bn_trapped_sellers_at_support"] = (trap_sell_raw & df["near_support_level"].values).astype(np.int8)
    else:
        df["bn_trapped_sellers_at_support"] = 0

    df["n_trapped_buyers_zones_active"] = n_buy_active
    df["n_trapped_sellers_zones_active"] = n_sell_active
    df["dist_trapped_buyers_nearest_pct"] = dist_buy
    df["dist_trapped_sellers_nearest_pct"] = dist_sell
    df["n_trapped_buyers_cluster_within_0_2pct"] = n_buy_cluster
    df["n_trapped_sellers_cluster_within_0_2pct"] = n_sell_cluster
    return df


def add_cluster_volume_features(df, footprint, symbol="ES", tick=TICK_SIZE):
    """
    BN #9 Cluster Volume (Chart 1 ES ID 10 + Chart 2 NQ ID 12).
    Volume At Price Threshold Alert V2 - Comparison Method = Total Volume.

    SC params officielles Jackson 27/04 :
      ES Volume Threshold = 250, Min Group Size = 2
      NQ Volume Threshold = 20,  Min Group Size = 2
      Draw Extension Lines until End of Chart = Yes (zones jusqu'a touche prix)

    Logique : scan cellules par bar, marker celles avec total_vol >= threshold,
    detecter groupes >= 2 cellules consecutives = "cluster" (battle ground).

    Trading : cluster touche par HIGH = resistance immediate ; touche par LOW = support.
    Cluster au milieu de la bar = niveau d'activite (POC local).

    Features generees (5) :
      n_cluster_groups   : nb de clusters dans la bar (groupes >= 2 cellules)
      max_cluster_size   : taille (nb cellules) du plus gros cluster dans la bar
      max_cluster_volume : volume total du plus gros cluster (ASK+BID somme)
      cluster_at_high    : 1 si un cluster touche le HIGH du bar (resistance)
      cluster_at_low     : 1 si un cluster touche le LOW du bar (support)
    """
    df = df.copy()
    sym = symbol.upper().split(".")[0]
    threshold = CLUSTER_VOLUME_THRESHOLD.get(sym, 250)
    min_group = CLUSTER_VOLUME_MIN_GROUP

    n = len(df)
    n_groups = np.zeros(n, dtype=np.int32)
    max_size = np.zeros(n, dtype=np.int32)
    max_vol = np.zeros(n, dtype=np.int32)
    at_high = np.zeros(n, dtype=np.int8)
    at_low = np.zeros(n, dtype=np.int8)

    high_arr = df["high"].values
    low_arr = df["low"].values

    for i in range(n):
        cells = footprint.get(i, {})
        if not cells:
            continue

        # Scan cellules : marker celles avec total_vol >= threshold
        prices_sorted = sorted(cells.keys())
        is_qualified = []
        for p in prices_sorted:
            tv = cells[p].get("total_vol", 0)
            is_qualified.append(tv >= threshold)

        # Detecter runs >= min_group consecutives qualifiees
        runs = []  # list of (start_idx, end_idx, total_vol)
        cur_start = None
        cur_total = 0
        for idx, q in enumerate(is_qualified):
            # Verifier consecutivite (pas de gap > tick)
            if q and (idx == 0 or abs(prices_sorted[idx] - prices_sorted[idx-1] - tick) < 1e-6 or cur_start is None):
                if cur_start is None:
                    cur_start = idx
                    cur_total = cells[prices_sorted[idx]]["total_vol"]
                else:
                    cur_total += cells[prices_sorted[idx]]["total_vol"]
            else:
                if cur_start is not None and (idx - cur_start) >= min_group:
                    runs.append((cur_start, idx - 1, cur_total))
                if q:
                    cur_start = idx
                    cur_total = cells[prices_sorted[idx]]["total_vol"]
                else:
                    cur_start = None
                    cur_total = 0
        # Final run
        if cur_start is not None:
            run_size = len(prices_sorted) - cur_start
            if run_size >= min_group:
                runs.append((cur_start, len(prices_sorted) - 1, cur_total))

        n_groups[i] = len(runs)
        if runs:
            sizes = [r[1] - r[0] + 1 for r in runs]
            vols = [r[2] for r in runs]
            max_size[i] = max(sizes)
            max_vol[i] = max(vols)

            # cluster_at_high / cluster_at_low : check si un cluster touche H ou L
            bar_h = high_arr[i]
            bar_l = low_arr[i]
            for r_start, r_end, _ in runs:
                p_min = prices_sorted[r_start]
                p_max = prices_sorted[r_end]
                if p_min <= bar_h <= p_max + tick / 2:
                    at_high[i] = 1
                if p_min - tick / 2 <= bar_l <= p_max:
                    at_low[i] = 1

    df["n_cluster_groups"] = n_groups
    df["max_cluster_size"] = max_size
    df["max_cluster_volume_v2"] = max_vol
    df["cluster_at_high"] = at_high
    df["cluster_at_low"] = at_low
    return df


def add_absorption_features(df, footprint, symbol="ES", tick=TICK_SIZE):
    """
    BN #6 Absorption Ask/Bid (Chart 1 ES ID 25/26 + Chart 2 NQ ID 29/30).

    SC formule officielle Jackson 27/04 :
      ABSORPTION ASK = AND(O > C[-1], AVAP(H,0) > BVAP(H,0)*3, AVAP(H,0) > 10)
      ABSORPTION BID = AND(O < C[-1], BVAP(L,0) > AVAP(L,0)*3, BVAP(L,0) > 20)

    Logique trading (Jackson) : absorption au milieu de nulle part = bruit,
    absorption SUR un niveau cle (MenthorQ, swing, VWAP, prev_vah, etc.) = tres puissant.

    6 features generees :
      bn_absorb_ask_raw       : pure SC formula (rare ~0.07% ES)
      bn_absorb_bid_raw       : idem
      near_resistance_level   : close <= proximity_ticks d'une resistance (any)
      near_support_level      : close <= proximity_ticks d'un support (any)
      bn_absorb_ask_at_level  : raw AND near_resistance (signal pro)
      bn_absorb_bid_at_level  : raw AND near_support
    """
    df = df.copy()
    sym = symbol.upper().split(".")[0]
    proximity_ticks = ABSORPTION_PROXIMITY_TICKS.get(sym, 10)
    proximity = proximity_ticks * tick
    # 06/05 : seuils calibres par sym (NQ moins liquide, seuil divise par ~2.5)
    threshold_ask = ABSORPTION_THRESHOLD_ASK_BY_SYM.get(sym, ABSORPTION_THRESHOLD_ASK)
    threshold_bid = ABSORPTION_THRESHOLD_BID_BY_SYM.get(sym, ABSORPTION_THRESHOLD_BID)

    n = len(df)
    abs_ask_raw = np.zeros(n, dtype=np.int8)
    abs_bid_raw = np.zeros(n, dtype=np.int8)
    near_res = np.zeros(n, dtype=np.int8)
    near_sup = np.zeros(n, dtype=np.int8)

    # Niveaux ABSOLUS disponibles (skip cols absentes ou tout-NaN)
    res_cols = [c for c in ABSORPTION_RESISTANCE_LEVELS if c in df.columns]
    sup_cols = [c for c in ABSORPTION_SUPPORT_LEVELS if c in df.columns]

    # MenthorQ niveaux DISTANCES PCT (dans v4_enriched comme dist_mq_*_pct)
    # Conversion : abs(dist_pct) <= proximity_ticks_in_pct(close)
    # On utilise per-bar : threshold_pct_per_bar = proximity_ticks * tick / close * 100
    mq_resistance_dist_cols = [c for c in ["dist_mq_call_pct", "dist_mq_call_0dte_pct"] if c in df.columns]
    mq_support_dist_cols = [c for c in ["dist_mq_put_pct", "dist_mq_put_0dte_pct"] if c in df.columns]
    # mq_hvl ambivalent (support OU resistance selon contexte) -> ajoute au 2 (signal moins selectif mais utile)
    mq_neutral_dist_cols = [c for c in ["dist_mq_hvl_pct", "dist_mq_hvl_pct_z"] if c in df.columns]

    high_arr = df["high"].values
    low_arr = df["low"].values
    open_arr = df["open"].values
    close_arr = df["close"].values
    res_vals = {c: df[c].values for c in res_cols}
    sup_vals = {c: df[c].values for c in sup_cols}
    mq_res_vals = {c: df[c].values for c in mq_resistance_dist_cols}
    mq_sup_vals = {c: df[c].values for c in mq_support_dist_cols}
    mq_neu_vals = {c: df[c].values for c in mq_neutral_dist_cols}

    for i in range(n):
        if i == 0:
            continue
        c_prev = close_arr[i-1]
        bar_high = high_arr[i]
        bar_low = low_arr[i]
        bar_open = open_arr[i]
        close = close_arr[i]
        cells = footprint.get(i, {})

        # Absorption ASK raw : O>C[-1] AND AskVol(top zone) > 3*BidVol(top zone) AND AskVol(top zone) > seuil
        # FIX 05/05/2026 : scan top zone = [H, H-tick] (2 cellules) au lieu de H exact.
        # Cause : le PRIX EXACT du high est souvent une meche d'1 trade,
        # les gros volumes d'absorption se trouvent typiquement a H ou H-tick.
        # Sierra Chart formule officielle AVAP(H,0) capture la cellule top du
        # footprint visuel — equivalent au max sur les 2 cellules au top.
        # Empirique : sans fix ES 0.067%, attendu ES 0.5-1.5% post-fix.
        if cells and bar_open > c_prev:
            ask_h = 0.0
            bid_h = 0.0
            for k in (0, 1):
                p = round((bar_high - tick * k) / tick) * tick
                cell_p = cells.get(p)
                if cell_p:
                    ask_h += cell_p.get("ask_vol", 0)
                    bid_h += cell_p.get("bid_vol", 0)
            if ask_h > bid_h * ABSORPTION_RATIO and ask_h > threshold_ask:
                abs_ask_raw[i] = 1

        # Absorption BID raw : O<C[-1] AND BidVol(bottom zone) > 3*AskVol(bottom zone) AND BidVol(bottom zone) > seuil
        # Idem fix : scan zone bottom [L, L+tick]
        if cells and bar_open < c_prev:
            ask_l = 0.0
            bid_l = 0.0
            for k in (0, 1):
                p = round((bar_low + tick * k) / tick) * tick
                cell_p = cells.get(p)
                if cell_p:
                    ask_l += cell_p.get("ask_vol", 0)
                    bid_l += cell_p.get("bid_vol", 0)
            if bid_l > ask_l * ABSORPTION_RATIO and bid_l > threshold_bid:
                abs_bid_raw[i] = 1

        # Near resistance/support : close +/- proximity de UN des niveaux ABSOLUS
        for c in res_cols:
            lvl = res_vals[c][i]
            if not np.isnan(lvl) and abs(lvl - close) <= proximity:
                near_res[i] = 1
                break
        for c in sup_cols:
            lvl = sup_vals[c][i]
            if not np.isnan(lvl) and abs(lvl - close) <= proximity:
                near_sup[i] = 1
                break

        # Niveaux MQ via dist_pct (proximity_ticks converted to pct per-bar)
        # Threshold per-bar : (proximity_ticks * tick / close) * 100
        proximity_pct_bar = (proximity / close) * 100 if close > 0 else 0
        if near_res[i] == 0:  # only check si pas deja flag par niveaux absolus
            for c in mq_resistance_dist_cols:
                d = mq_res_vals[c][i]
                if not np.isnan(d) and abs(d) <= proximity_pct_bar:
                    near_res[i] = 1
                    break
            # mq_hvl ambivalent : verifie aussi resistance (close approche par-dessous)
            if near_res[i] == 0:
                for c in mq_neutral_dist_cols:
                    d = mq_neu_vals[c][i]
                    if not np.isnan(d) and abs(d) <= proximity_pct_bar:
                        near_res[i] = 1
                        break
        if near_sup[i] == 0:
            for c in mq_support_dist_cols:
                d = mq_sup_vals[c][i]
                if not np.isnan(d) and abs(d) <= proximity_pct_bar:
                    near_sup[i] = 1
                    break
            if near_sup[i] == 0:
                for c in mq_neutral_dist_cols:
                    d = mq_neu_vals[c][i]
                    if not np.isnan(d) and abs(d) <= proximity_pct_bar:
                        near_sup[i] = 1
                        break

    df["bn_absorb_ask_raw"] = abs_ask_raw
    df["bn_absorb_bid_raw"] = abs_bid_raw
    df["near_resistance_level"] = near_res
    df["near_support_level"] = near_sup
    df["bn_absorb_ask_at_level"] = (abs_ask_raw & near_res).astype(np.int8)
    df["bn_absorb_bid_at_level"] = (abs_bid_raw & near_sup).astype(np.int8)
    return df


PHASE_B_PLUS_PLUS_GENERATED = {
    # Big orders multi-tier
    "n_big_t1", "n_big_t2", "n_big_t3", "n_big_t4",
    "n_big_buy_t1", "n_big_buy_t2", "n_big_buy_t3", "n_big_buy_t4",
    "n_big_sell_t1", "n_big_sell_t2", "n_big_sell_t3", "n_big_sell_t4",
    # Trade size stats
    "max_size_buy", "max_size_sell", "p99_trade_size",
    # Aggressor + clusters
    "aggressor_imbalance", "n_clusters", "max_cluster_volume",
    # Derivees rapport tier (proxy absorption)
    "big_buy_dominance", "big_sell_dominance",
    # FPBS subgraphs intra-bar (NOUVEAU - D.1)
    "max_delta_bar", "min_delta_bar", "delta_change", "n_ticks_bar",
    "finish_pct_up", "finish_strong_up", "finish_strong_dn",
    # NOTE rotation_up/rotation_dn deplaces dans phase_b_plus_engine.py (formule SC OHLC pure)
    # BN #6 Absorption Ask/Bid (formule SC officielle + at_level contextualise)
    "bn_absorb_ask_raw", "bn_absorb_bid_raw",
    "near_resistance_level", "near_support_level",
    "bn_absorb_ask_at_level", "bn_absorb_bid_at_level",
    # BN #7 Double ES (2 cellules) / Triple NQ (3 cellules) : stack PUR ASK/BID
    "bn_stack_ask", "bn_stack_bid",
    # BN #8 Big Orders multi-tier v2 (formule SC officielle scan cellules VAP, pas trade aggregat)
    "n_big_ask_v2_t1", "n_big_ask_v2_t2", "n_big_ask_v2_t3", "n_big_ask_v2_t4",
    "n_big_bid_v2_t1", "n_big_bid_v2_t2", "n_big_bid_v2_t3", "n_big_bid_v2_t4",
    "max_big_ask_vol_in_bar", "max_big_bid_vol_in_bar",
    # BN #9 Cluster Volume (Total Volume + min 2 cellules consecutives)
    "n_cluster_groups", "max_cluster_size", "max_cluster_volume_v2",
    "cluster_at_high", "cluster_at_low",
    # Delta Divergence buy/sell (NOUVEAU - G.1, formule daily OHLC + delta_bar)
    "delta_div_buy", "delta_div_sell",
    # BN #12 Delta Divergence Extension Lines (zones support/resistance persistantes + clusters)
    "n_delta_div_buy_zones_active", "n_delta_div_sell_zones_active",
    "dist_delta_div_buy_nearest_pct", "dist_delta_div_sell_nearest_pct",
    "n_delta_div_buy_cluster_within_0_2pct", "n_delta_div_sell_cluster_within_0_2pct",
    # Distance big orders / clusters nearest pct (NOUVEAU - B.1/B.2 complet)
    "dist_big_ask_nearest_pct", "dist_big_bid_nearest_pct",
    "dist_cluster_nearest_up_pct", "dist_cluster_nearest_dn_pct",
    # BN bonus Trapped Traders (raw + at_level + Extension Lines + clusters)
    "bn_trapped_buyers_raw", "bn_trapped_sellers_raw",
    "bn_trapped_buyers_at_resistance", "bn_trapped_sellers_at_support",
    "n_trapped_buyers_zones_active", "n_trapped_sellers_zones_active",
    "dist_trapped_buyers_nearest_pct", "dist_trapped_sellers_nearest_pct",
    "n_trapped_buyers_cluster_within_0_2pct", "n_trapped_sellers_cluster_within_0_2pct",
}


def apply_phase_b_plus_plus(df: pd.DataFrame, trades_df: Optional[pd.DataFrame],
                              symbol: str = "ES",
                              tick: float = TICK_SIZE) -> pd.DataFrame:
    """
    Applique Phase B+++ : big orders + clusters + aggressor depuis Trades agreges.

    Si trades_df vide ou None : ajoute toutes les colonnes a 0/NaN.
    """
    df = df.copy()
    drop_existing = [c for c in PHASE_B_PLUS_PLUS_GENERATED if c in df.columns]
    if drop_existing:
        df = df.drop(columns=drop_existing)

    sym = symbol.upper().split(".")[0]
    tier_thresholds = BIG_ORDER_TIERS.get(sym, BIG_ORDER_TIERS["ES"])
    cluster_threshold = CLUSTER_THRESHOLDS.get(sym, CLUSTER_THRESHOLDS["ES"])

    # Cas no trades : initialise a 0
    if trades_df is None or trades_df.empty:
        for col in PHASE_B_PLUS_PLUS_GENERATED:
            df[col] = 0 if col != "aggressor_imbalance" else 0.0
        return df

    # Aggregate (passe bar_close pour distance computations)
    bar_aggs = aggregate_trades_per_bar(
        trades_df, df["ts_event"], tier_thresholds, cluster_threshold,
        bar_close=df["close"], tick=tick
    )
    if bar_aggs.empty:
        for col in PHASE_B_PLUS_PLUS_GENERATED:
            df[col] = 0 if col != "aggressor_imbalance" else 0.0
        return df

    # Reindex on full df (some bars may have no trades)
    bar_aggs = bar_aggs.reindex(range(len(df)), fill_value=0)
    for col in bar_aggs.columns:
        df[col] = bar_aggs[col].values

    # Derivees : big_buy_dominance = n_big_buy / max(n_big_buy + n_big_sell, 1) sur tier 1
    total_big = df["n_big_buy_t1"] + df["n_big_sell_t1"]
    df["big_buy_dominance"] = (df["n_big_buy_t1"] / total_big.replace(0, np.nan)).fillna(0.5).astype("float32")
    df["big_sell_dominance"] = (df["n_big_sell_t1"] / total_big.replace(0, np.nan)).fillna(0.5).astype("float32")

    # Cast counts en int32 (mais pas les distances pct)
    int_cols = [c for c in bar_aggs.columns if c.startswith("n_") or c.startswith("max_")]
    for c in int_cols:
        if not c.endswith("_pct"):
            df[c] = df[c].astype("int32")

    # FPBS derivees (D.1) : delta_change, finish_pct_up, finish_strong
    df["delta_change"] = df["delta_bar"].diff().fillna(0).astype("float32")
    bar_range = (df["high"] - df["low"]).replace(0, np.nan)
    df["finish_pct_up"] = ((df["close"] - df["low"]) / bar_range * 100).fillna(50).astype("float32")
    df["finish_strong_up"] = (df["finish_pct_up"] >= 80).astype("int8")
    df["finish_strong_dn"] = (df["finish_pct_up"] <= 20).astype("int8")

    # NOTE Rotation (A.5) DEPLACE dans phase_b_plus_engine.py (formule SC officielle OHLC pure)
    # Delta Divergence buy/sell (G.1) : daily OHLC + delta_bar
    # daily_low_running < prev_day_low ET delta_bar >= 0 -> divergence bullish
    if "ts_event" in df.columns:
        ts_et = df["ts_event"].dt.tz_convert("America/New_York") if df["ts_event"].dt.tz else df["ts_event"].dt.tz_localize("UTC").dt.tz_convert("America/New_York")
        date_et_local = ts_et.dt.date
        df["__daily_high_running"] = df.groupby(date_et_local)["high"].cummax()
        df["__daily_low_running"] = df.groupby(date_et_local)["low"].cummin()
        # Previous day high/low
        daily_agg = pd.DataFrame({
            "d_high": df.groupby(date_et_local)["high"].max(),
            "d_low": df.groupby(date_et_local)["low"].min(),
        })
        daily_agg["prev_d_high"] = daily_agg["d_high"].shift(1)
        daily_agg["prev_d_low"] = daily_agg["d_low"].shift(1)
        df["__date_local"] = date_et_local
        df = df.merge(daily_agg[["prev_d_high", "prev_d_low"]],
                       left_on="__date_local", right_index=True, how="left")
        df["delta_div_buy"] = (
            (df["__daily_low_running"] < df["prev_d_low"]) & (df["delta_bar"] >= 0)
        ).fillna(False).astype("int8")
        df["delta_div_sell"] = (
            (df["__daily_high_running"] > df["prev_d_high"]) & (df["delta_bar"] <= 0)
        ).fillna(False).astype("int8")
        # Cleanup helpers temp
        df.drop(columns=["__daily_high_running", "__daily_low_running",
                          "__date_local", "prev_d_high", "prev_d_low"],
                 errors="ignore", inplace=True)

        # BN #12 Delta Divergence EXTENSION LINES (formule SC : Draw Extension Lines = Yes)
        # delta_div_buy fire bar i -> zone SUPPORT au LOW de la bar
        # delta_div_sell fire bar i -> zone RESISTANCE au HIGH de la bar
        # Zones persistent jusqu'a touche prix futur (overlap [low, high] avec zone)
        df = add_delta_div_extension_lines(df)

        # 06/05 fix Jackson : add_long_color_extension_lines() codee pour LONG_UP/DN
        # + COLOR_UP/DN. EN ATTENTE fix triggers source DMP — actuellement
        # bar_long_*/bn_color_* absents en mode --use-mq-lite (pipeline live).
        # A activer apres fix C++ DMP_ReadExtensionLineCount (action backlog
        # incident_log 06/05 — meme pattern fix delta_div 07/04).
        # Decommenter ligne suivante quand triggers source dispo :
        # df = add_long_color_extension_lines(df)

    # BN #6 Absorption + BN #7 Stack + BN #8 Big Orders v2 + BN #9 Cluster Volume
    # Toutes necessitent footprint cellule
    if trades_df is not None and not trades_df.empty:
        from footprint_builder import build_footprint_per_bar
        footprint = build_footprint_per_bar(trades_df, df["ts_event"], tick=tick)
        df = add_absorption_features(df, footprint, symbol=symbol, tick=tick)
        df = add_stack_features(df, footprint, symbol=symbol, tick=tick)
        df = add_big_orders_features_v2(df, footprint, symbol=symbol, tick=tick)
        df = add_cluster_volume_features(df, footprint, symbol=symbol, tick=tick)
        # BN bonus Trapped Traders (apres absorption pour reuse near_resistance/support)
        df = add_trapped_traders_features(df, footprint, symbol=symbol, tick=tick)
    else:
        for col in ["bn_absorb_ask_raw", "bn_absorb_bid_raw",
                     "near_resistance_level", "near_support_level",
                     "bn_absorb_ask_at_level", "bn_absorb_bid_at_level",
                     "bn_stack_ask", "bn_stack_bid",
                     "n_big_ask_v2_t1", "n_big_ask_v2_t2", "n_big_ask_v2_t3", "n_big_ask_v2_t4",
                     "n_big_bid_v2_t1", "n_big_bid_v2_t2", "n_big_bid_v2_t3", "n_big_bid_v2_t4",
                     "max_big_ask_vol_in_bar", "max_big_bid_vol_in_bar",
                     "n_cluster_groups", "max_cluster_size", "max_cluster_volume_v2",
                     "cluster_at_high", "cluster_at_low",
                     "bn_trapped_buyers_raw", "bn_trapped_sellers_raw",
                     "bn_trapped_buyers_at_resistance", "bn_trapped_sellers_at_support",
                     "n_trapped_buyers_zones_active", "n_trapped_sellers_zones_active",
                     "n_trapped_buyers_cluster_within_0_2pct", "n_trapped_sellers_cluster_within_0_2pct"]:
            df[col] = 0
        # dist_*_pct : NaN par convention quand aucune zone active
        df["dist_trapped_buyers_nearest_pct"] = np.nan
        df["dist_trapped_sellers_nearest_pct"] = np.nan

    return df
