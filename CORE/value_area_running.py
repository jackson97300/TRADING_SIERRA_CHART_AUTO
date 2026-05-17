"""
value_area_running.py — Phase C : VPOC/VAH/VAL running cumsum (V4-natif)

Calcule cur_vpoc/vah/val/inside_value_area en RUNNING par bar (cumulatif depuis
debut de session), depuis trades Databento. Remplace le calcul EOD broadcast
de phase_b_helpers.add_volume_profile_features qui souffrait d'un lookahead
intraday documente (ML_EXCLUDE_FEATURES ligne 165-169).

Algo Steidlmayer expand-from-POC outward, identique a compute_volume_profile_dict
de phase_b_helpers.py pour garantir convergence EOD bit-for-bit (test de parite).

Usage :
    df = apply_value_area_running(df, trades_df, symbol="ES", tick=0.25)

Effets :
  - Ecrase cur_vpoc, cur_vah, cur_val (running au lieu d'EOD)
  - Ecrase inside_value_area (recalcul depuis cur_vah/val running)
  - Ecrase dist_cur_vpoc_pct, dist_cur_vah_pct, dist_cur_val_pct (recalcul)
  - Pose cur_va_n_buckets (diagnostic : nb prix uniques dans la session)
  - Pose cur_va_total_vol (diagnostic : volume cumule session)

Convention session : session_date_trading (CME, dim 18:00 ET -> ven 17:00 ET)
deja calcule par add_session_metadata. Reset cumulatif a chaque nouvelle session.

Pas de lookahead : a la barre i, cur_vpoc[i] reflete uniquement les trades avec
ts_event <= bar_i.end_ts (= bar_i.start_ts + 1 minute).

Auteur : Phase C V4 (2026-04-27)
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

TICK_SIZE = 0.25  # default ES/NQ. MGC=0.10 — caller passe tick explicitement
VALUE_AREA_PCT = 70.0


def _compute_va_from_arrays(
    volumes: np.ndarray,
    prices: np.ndarray,
    target_pct: float = VALUE_AREA_PCT,
) -> tuple[float, float, float]:
    """
    Algo Steidlmayer expand-from-POC outward. Identique a compute_volume_profile_dict
    de phase_b_helpers.py pour garantir convergence EOD.

    Args:
        volumes : np.array float64, volumes cumules par bucket (ordre = prices)
        prices  : np.array float64, prix tries ascending (correspond a volumes)
        target_pct : % du volume total cible (70% standard)
    Returns:
        (vpoc, vah, val)
    """
    if volumes.size == 0:
        return np.nan, np.nan, np.nan
    total_vol = volumes.sum()
    if total_vol <= 0:
        return np.nan, np.nan, np.nan

    target_vol = total_vol * target_pct / 100.0
    poc_idx = int(np.argmax(volumes))
    vpoc = float(prices[poc_idx])
    cum_vol = float(volumes[poc_idx])
    lo, hi = poc_idx, poc_idx
    n = volumes.size

    while cum_vol < target_vol and (lo > 0 or hi < n - 1):
        v_up = float(volumes[hi + 1]) if hi < n - 1 else -1.0
        v_dn = float(volumes[lo - 1]) if lo > 0 else -1.0
        if v_up >= v_dn:
            hi += 1
            cum_vol += v_up
        else:
            lo -= 1
            cum_vol += v_dn

    return vpoc, float(prices[hi]), float(prices[lo])


def apply_value_area_running(
    df: pd.DataFrame,
    trades_df: Optional[pd.DataFrame] = None,
    *,
    symbol: str = "ES",
    tick: float = TICK_SIZE,
    value_area_pct: float = VALUE_AREA_PCT,
) -> pd.DataFrame:
    """
    Recalcule cur_vpoc/vah/val/inside_value_area en RUNNING.

    Convention boundary : bars sont des intervalles [ts_event, ts_event + 60s).
    Un trade au timestamp exact d'une bar boundary est attribue a la bar SUIVANTE
    (start de la bar suivante = trade a `bar_starts[k]` -> bar k, pas k-1).
    Implementation : `searchsorted(side="right") - 1` (cf L160).

    Args:
        df : v4_enriched apres add_all_phase_b_helpers (a au moins ts_event,
             session_date_trading, close). L'index doit etre RangeIndex 0..n-1
             (sinon la fonction le reset defensivement).
        trades_df : trades Databento (ts_event, price, size). Si None ou empty,
                    fail-loud (pas de fallback silencieux).
        symbol : ES ou NQ (pour log)
        tick : tick size (0.25 ES + NQ)
        value_area_pct : 70.0 standard

    Returns:
        DataFrame avec cur_vpoc/vah/val running, inside_value_area running,
        dist_cur_*_pct running. Les autres cols inchangees.
    """
    if trades_df is None or trades_df.empty:
        raise ValueError(
            "[Phase C VPOC running] trades_df vide ou None. "
            "Phase C exige trades Databento pour calculer VAP running. "
            "Pas de fallback OHLC accepte (silent failure documente lessons.md)."
        )

    df = df.copy()
    # FIX MAJEUR 1 (code-reviewer 27/04) : reset_index defensif.
    # apply_value_area_running indexe out_vpoc[bar_i] positionnellement (0..n-1).
    # Si l'appelant passe un df avec index non-trivial (ex: filtrage prealable
    # sans reset_index), bar_i ne matchera plus l'array out -> bug silencieux.
    if not df.index.equals(pd.RangeIndex(len(df))):
        df = df.reset_index(drop=True)

    required_cols = {"ts_event", "session_date_trading", "close"}
    missing = required_cols - set(df.columns)
    if missing:
        raise KeyError(
            f"[Phase C VPOC running] colonnes manquantes dans df : {missing}. "
            f"Appeler add_all_phase_b_helpers() avant apply_value_area_running()."
        )

    n_bars = len(df)
    if n_bars == 0:
        raise ValueError("[Phase C VPOC running] df vide.")

    # ─── Etape 1 : Bin trades to bar via searchsorted sur ts_event ──
    trades_sorted = trades_df.sort_values("ts_event").reset_index(drop=True)
    bar_starts = df["ts_event"].values  # deja trie ascending dans v4_enriched

    # Cast ts en int64 ns pour searchsorted (evite tz issues)
    if hasattr(bar_starts, "dtype") and "datetime" in str(bar_starts.dtype):
        bar_starts_ns = bar_starts.astype("datetime64[ns]").astype(np.int64)
    else:
        bar_starts_ns = pd.to_datetime(bar_starts).values.astype(np.int64)

    trade_ts_ns = trades_sorted["ts_event"].values.astype("datetime64[ns]").astype(np.int64)
    # bar_idx = derniere bar dont start <= trade_ts
    # side='right' - 1 = trade strictement avant ou egal au start prochain
    bar_idx = np.searchsorted(bar_starts_ns, trade_ts_ns, side="right") - 1
    valid = bar_idx >= 0
    trades_sorted = trades_sorted.loc[valid].copy()
    trades_sorted["bar_idx"] = bar_idx[valid]

    # ─── Etape 2 : bucketize price ──
    trades_sorted["price_bucket"] = (trades_sorted["price"] / tick).round() * tick

    # ─── Etape 3 : Pre-aggreger volumes par (bar_idx, price_bucket) ──
    # Une seule passe groupby evite de re-iterer trades dans la boucle bars
    bar_price_vol = (
        trades_sorted.groupby(["bar_idx", "price_bucket"], sort=True)["size"]
        .sum()
        .astype("float64")
    )
    # bar_price_vol est un Series MultiIndex (bar_idx, price_bucket) -> volume

    # Index par bar_idx pour iteration rapide
    bar_idx_unique = bar_price_vol.index.get_level_values(0).unique()
    bar_idx_set = set(bar_idx_unique.tolist())

    # ─── Etape 4 : Boucle par session, cumul VAP, calcul VPOC/VA running ──
    out_vpoc = np.full(n_bars, np.nan, dtype=np.float64)
    out_vah = np.full(n_bars, np.nan, dtype=np.float64)
    out_val = np.full(n_bars, np.nan, dtype=np.float64)
    out_n_buckets = np.zeros(n_bars, dtype=np.int32)
    out_total_vol = np.zeros(n_bars, dtype=np.float64)

    sess_groups = df.groupby("session_date_trading", sort=True)

    for sess_date, sess_df in sess_groups:
        cum_vap: dict[float, float] = {}  # price_bucket -> cumulative volume
        bars_in_sess = sess_df.index.to_numpy()

        # Tracker dernieres valeurs pour forward-fill bars sans trades
        last_vpoc = np.nan
        last_vah = np.nan
        last_val = np.nan

        for bar_i in bars_in_sess:
            # Add trades de cette bar au cum_vap
            if bar_i in bar_idx_set:
                # bar_price_vol.loc[bar_i] retourne Series (price_bucket -> volume)
                bar_data = bar_price_vol.loc[bar_i]
                # MultiIndex groupby retourne TOUJOURS Series (jamais scalar) pour bar_i present
                for price, v in bar_data.items():
                    cum_vap[price] = cum_vap.get(price, 0.0) + float(v)

            if not cum_vap:
                # Bar sans trades : forward-fill (incluant diagnostics pour coherence)
                out_vpoc[bar_i] = last_vpoc
                out_vah[bar_i] = last_vah
                out_val[bar_i] = last_val
                # FIX MINEUR 4 (code-reviewer) : forward-fill aussi diagnostics
                if bar_i > 0:
                    out_n_buckets[bar_i] = out_n_buckets[bar_i - 1]
                    out_total_vol[bar_i] = out_total_vol[bar_i - 1]
                continue

            # Convertir cum_vap dict en arrays sortes pour _compute_va_from_arrays
            prices_arr = np.array(sorted(cum_vap.keys()), dtype=np.float64)
            volumes_arr = np.array([cum_vap[p] for p in prices_arr], dtype=np.float64)

            vpoc, vah, val = _compute_va_from_arrays(volumes_arr, prices_arr, value_area_pct)
            out_vpoc[bar_i] = vpoc
            out_vah[bar_i] = vah
            out_val[bar_i] = val
            out_n_buckets[bar_i] = len(prices_arr)
            out_total_vol[bar_i] = volumes_arr.sum()
            last_vpoc, last_vah, last_val = vpoc, vah, val

    # ─── Etape 5 : Ecrire dans df ──
    df["cur_vpoc"] = out_vpoc
    df["cur_vah"] = out_vah
    df["cur_val"] = out_val
    df["cur_va_n_buckets"] = out_n_buckets
    df["cur_va_total_vol"] = out_total_vol

    # Recalcul derivees
    df["inside_value_area"] = (
        (df["close"] >= df["cur_val"]) & (df["close"] <= df["cur_vah"])
    ).astype("int8")

    close_safe = df["close"].replace(0, np.nan)
    # 17/05 FIX REGRESSION BUG D (commit 78f40cb 15/05) : convention unifiee
    # `(level - close) / close * 100` compliant DMP C++ (positif = niveau
    # AU-DESSUS du close). Avant : `(close - level)` = convention inverse,
    # non-aligne avec phase_b_helpers.py:1205-1207 + audit_tpsl_walls +
    # bot3_*_level_definitions qui utilisent tous (level - close).
    # Module value_area_running.py etait seul out-of-sync = regression silente.
    df["dist_cur_vpoc_pct"] = ((df["cur_vpoc"] - df["close"]) / close_safe * 100).astype("float32")
    df["dist_cur_vah_pct"]  = ((df["cur_vah"] - df["close"]) / close_safe * 100).astype("float32")
    df["dist_cur_val_pct"]  = ((df["cur_val"] - df["close"]) / close_safe * 100).astype("float32")

    return df


# ═══════════════════════════════════════════════════════════════════════════════
# Diagnostic / sanity checks (utilitaires hors pipeline)
# ═══════════════════════════════════════════════════════════════════════════════

def check_va_invariants(df: pd.DataFrame) -> dict:
    """
    Verifie les invariants Value Area :
      - cur_val <= cur_vpoc <= cur_vah
      - inside_value_area = 1 ssi cur_val <= close <= cur_vah

    Returns:
        dict avec stats violations (0 = OK)
    """
    valid = df.dropna(subset=["cur_vpoc", "cur_vah", "cur_val"])
    n_valid = len(valid)
    n_violation_order = (~((valid["cur_val"] <= valid["cur_vpoc"]) & (valid["cur_vpoc"] <= valid["cur_vah"]))).sum()
    expected_inside = ((valid["close"] >= valid["cur_val"]) & (valid["close"] <= valid["cur_vah"])).astype("int8")
    n_violation_inside = (valid["inside_value_area"] != expected_inside).sum()
    return {
        "n_bars_valid": int(n_valid),
        "n_violation_order": int(n_violation_order),
        "n_violation_inside_value_area": int(n_violation_inside),
        "ok": bool(n_violation_order == 0 and n_violation_inside == 0),
    }
