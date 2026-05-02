"""
labeler_v3.py — Triple Barrier Lopez AFML ch.3 STRICT

Created : 2026-05-02 samedi 0bis
Author : Jackson + audit ml-trainer + market-analyst (2 agents convergents sur C v1)

Differences vs labeler v2 (DEGRADE) :
  v2 (degrade)               | v3 (Lopez strict)
  ---------------------------|-------------------------------
  TP/SL fixes ticks          | Vol-scaled `pt_sl × daily_vol[t]` (ch.3.1)
  Close proxy                | High/Low intrabar path detection (Databento)
  Walk-forward simple        | Purged k-fold + embargo (ch.7) — applique au train
  Pas de sample_weight       | Uniqueness Lopez ch.4
  Aucun pre-filter           | RVOL < 0.3 drop barres mortes (consensus 2 agents)
  Bars 1m uniquement         | Configurable TF (1m, 5m, 15m, 1h)

Conformite Lopez AFML :
  - ch.3.1 : Daily volatility estimate (EWMA returns)
  - ch.3.2 : Triple Barrier method (TP / SL / horizon)
  - ch.3.3 : Side-aware vs side-agnostic labels
  - ch.4   : Sample weights via uniqueness
  - ch.7   : Purged k-fold (applique a train_lightgbm.py, pas ici)

Output : DataFrame avec colonnes :
  - ts_event, label {-1, 0, +1}
  - t1 (timestamp barriere atteinte ou horizon expire)
  - barrier_type {tp, sl, vertical}
  - sample_weight (uniqueness Lopez ch.4)
  - daily_vol_at_entry (vol-scaled barrier reference)
"""

from __future__ import annotations
from typing import Optional
import numpy as np
import pandas as pd


# ═════════════════════════════════════════════════════════════════════
# DAILY VOLATILITY ESTIMATE (Lopez AFML ch.3.1)
# ═════════════════════════════════════════════════════════════════════

# Lopez AFML ch.3.1 strict : span = ~1 jour de bars (TF-dependent)
# Reviewed-by ml-trainer 02/05 : "5m → span=78 (pas 100)"
TF_SPANS = {
    '1m': 390,   # 390 bars RTH 1m / jour
    '5m': 78,    # 78 bars RTH 5m / jour
    '15m': 26,   # 26 bars RTH 15m / jour
    '1h': 7,     # 7 bars RTH 1h / jour
}


def compute_daily_vol(close: pd.Series, span: int = 78,
                       tf: Optional[str] = None) -> pd.Series:
    """
    Estime la volatilite journaliere via EWMA des returns log (Lopez AFML ch.3.1).

    Lopez AFML p.43 eq. 3.1 : "use a span equivalent to one day of bars".

    Args:
        close : pd.Series prix close indexed par ts_event
        span : EWMA span. Default 78 (5m bars RTH).
        tf : Override span via TF_SPANS dict (recommande). Si tf donne, ignore span.

    Returns:
        Series std des returns log scaled (vol pct par barre)
    """
    if tf is not None and tf in TF_SPANS:
        span = TF_SPANS[tf]
    if len(close) < span:
        return pd.Series(np.nan, index=close.index)

    # Returns log (Lopez prefer log returns vs simple)
    rets = np.log(close / close.shift(1))
    # EWMA std
    vol = rets.ewm(span=span, min_periods=span).std()
    return vol


# ═════════════════════════════════════════════════════════════════════
# VERTICAL BARRIER (horizon temporel)
# ═════════════════════════════════════════════════════════════════════

def compute_vertical_barriers(close: pd.Series, num_bars: int) -> pd.Series:
    """
    Pour chaque barre i, retourne ts_event de la barre i+num_bars (horizon).

    Args:
        close : Series indexee ts_event
        num_bars : nombre barres horizon (ex: 12 pour 5m bars = 1h)

    Returns:
        Series t1 : timestamp barriere verticale par barre.
        NaN pour barres ou horizon depasse fin du dataset.
    """
    t1 = close.index.to_series().shift(-num_bars)
    return t1


# ═════════════════════════════════════════════════════════════════════
# TRIPLE BARRIER PATH DETECTION (high/low intrabar)
# ═════════════════════════════════════════════════════════════════════

def apply_triple_barrier(df: pd.DataFrame,
                          events: pd.DataFrame,
                          pt_sl: tuple = (1.5, 1.0),
                          molecule: Optional[list] = None) -> pd.DataFrame:
    """
    Lopez AFML ch.3.2 — Triple Barrier avec path detection high/low intrabar.

    Args:
        df : DataFrame OHLCV avec colonnes 'high', 'low', 'close', indexed ts_event
        events : DataFrame indexed ts_event (entry timestamps) avec :
            - t1 : ts_event horizon (vertical barrier)
            - daily_vol : vol estime entry (scale les barriers)
        pt_sl : (tp_mult, sl_mult). Default (1.5, 1.0) = RR 1.5 conservateur.
        molecule : sous-ensemble entries a traiter (parallelisation).

    Returns:
        DataFrame indexed ts_event avec :
            - t1 : ts barriere atteinte (TP, SL, ou vertical)
            - barrier_type : {'tp', 'sl', 'vertical'}
            - tp_level, sl_level : niveaux prix barrieres (audit)
            - return_at_t1 : return du trade a la barriere atteinte
    """
    if molecule is None:
        molecule = events.index.tolist()

    out = events.loc[molecule, ['t1', 'daily_vol']].copy()
    out['tp_level'] = np.nan
    out['sl_level'] = np.nan
    out['barrier_type'] = 'vertical'
    out['return_at_t1'] = 0.0
    out['ts_t1_actual'] = out['t1']

    for entry_ts in molecule:
        if entry_ts not in df.index:
            continue
        vol_t = events.at[entry_ts, 'daily_vol']
        if pd.isna(vol_t) or vol_t <= 0:
            continue

        entry_price = df.at[entry_ts, 'close']
        # Vol-scaled barriers (Lopez ch.3.1)
        # vol_t = std relative log returns → multiplier prix par vol_t pct
        tp_level = entry_price * (1 + pt_sl[0] * vol_t)
        sl_level = entry_price * (1 - pt_sl[1] * vol_t)
        t1_vertical = events.at[entry_ts, 't1']

        # Slice path forward jusqu'au vertical
        if pd.isna(t1_vertical):
            path = df.loc[entry_ts:].iloc[1:]  # drop entry bar elle-meme
        else:
            path = df.loc[entry_ts:t1_vertical].iloc[1:]
        if path.empty:
            continue

        # Path detection high/low intrabar (Lopez recommande)
        # Trouve le premier ts ou high>=tp ou low<=sl
        hit_tp = path[path['high'] >= tp_level]
        hit_sl = path[path['low'] <= sl_level]

        first_tp = hit_tp.index[0] if not hit_tp.empty else None
        first_sl = hit_sl.index[0] if not hit_sl.empty else None

        if first_tp is not None and first_sl is not None:
            # Tie-break : la plus precoce
            if first_tp <= first_sl:
                out.at[entry_ts, 'barrier_type'] = 'tp'
                out.at[entry_ts, 'ts_t1_actual'] = first_tp
                out.at[entry_ts, 'return_at_t1'] = pt_sl[0] * vol_t
            else:
                out.at[entry_ts, 'barrier_type'] = 'sl'
                out.at[entry_ts, 'ts_t1_actual'] = first_sl
                out.at[entry_ts, 'return_at_t1'] = -pt_sl[1] * vol_t
        elif first_tp is not None:
            out.at[entry_ts, 'barrier_type'] = 'tp'
            out.at[entry_ts, 'ts_t1_actual'] = first_tp
            out.at[entry_ts, 'return_at_t1'] = pt_sl[0] * vol_t
        elif first_sl is not None:
            out.at[entry_ts, 'barrier_type'] = 'sl'
            out.at[entry_ts, 'ts_t1_actual'] = first_sl
            out.at[entry_ts, 'return_at_t1'] = -pt_sl[1] * vol_t
        else:
            # Vertical barrier hit, return = (close_t1 - entry) / entry
            if not pd.isna(t1_vertical) and t1_vertical in df.index:
                close_t1 = df.at[t1_vertical, 'close']
                out.at[entry_ts, 'return_at_t1'] = (close_t1 - entry_price) / entry_price

        out.at[entry_ts, 'tp_level'] = tp_level
        out.at[entry_ts, 'sl_level'] = sl_level

    return out


# ═════════════════════════════════════════════════════════════════════
# LABEL FROM BARRIERS (Lopez ch.3.3)
# ═════════════════════════════════════════════════════════════════════

def get_labels(events_with_barriers: pd.DataFrame,
                vertical_label_mode: str = 'lopez_strict') -> pd.DataFrame:
    """
    Lopez AFML ch.3.3 — Label {-1, 0, +1} from barrier_type.

    Side-agnostic version : pas de side a priori.
    - barrier_type = 'tp' → label +1 (long aurait gagne)
    - barrier_type = 'sl' → label -1 (short aurait gagne)
    - barrier_type = 'vertical' → label selon vertical_label_mode

    vertical_label_mode :
        'lopez_strict' (default, conforme AFML p.49) :
            label = sign(return_at_t1)
            Si return_at_t1 > 0 → +1, < 0 → -1, == 0 → 0 (rare)
        'with_neutral_threshold' (deviation documentee) :
            label = sign(return_at_t1) si |return| > 0.1 * daily_vol, sinon 0
            Justification : mouvement trop petit = pas tradable, force HOLD

    Args:
        events_with_barriers : output de apply_triple_barrier()
        vertical_label_mode : 'lopez_strict' ou 'with_neutral_threshold'

    Returns:
        DataFrame avec colonne 'label' added.
    """
    if vertical_label_mode not in ('lopez_strict', 'with_neutral_threshold'):
        raise ValueError(f"vertical_label_mode must be 'lopez_strict' or "
                         f"'with_neutral_threshold', got {vertical_label_mode}")

    out = events_with_barriers.copy()
    out['label'] = 0
    out.loc[out['barrier_type'] == 'tp', 'label'] = 1
    out.loc[out['barrier_type'] == 'sl', 'label'] = -1

    vertical = out['barrier_type'] == 'vertical'
    if vertical_label_mode == 'lopez_strict':
        # Lopez AFML ch.3.3 p.49 : sign(return_at_t1) pure, pas de seuil
        out.loc[vertical & (out['return_at_t1'] > 0), 'label'] = 1
        out.loc[vertical & (out['return_at_t1'] < 0), 'label'] = -1
        # return == 0 reste a label = 0 (cas degenere)
    else:
        # Deviation : seuil neutre = mouvement < 0.1 × daily_vol → HOLD
        threshold = 0.1 * out['daily_vol'].fillna(0)
        out.loc[vertical & (out['return_at_t1'].abs() < threshold), 'label'] = 0
        out.loc[vertical & (out['return_at_t1'] >= threshold), 'label'] = 1
        out.loc[vertical & (out['return_at_t1'] <= -threshold), 'label'] = -1
    return out


# ═════════════════════════════════════════════════════════════════════
# RVOL PRE-FILTER (consensus 2 agents — drop barres mortes)
# ═════════════════════════════════════════════════════════════════════

def filter_low_rvol(df: pd.DataFrame, rvol_threshold: float = 0.3,
                     volume_col: str = 'volume',
                     window_bars: int = 78) -> pd.DataFrame:
    """
    Drop barres ou rvol < threshold.

    rvol_t = volume_t / mean(volume_t-window:t)

    window_bars default 78 = 1 jour RTH 5m bars (ou ~6.5h liquid).
    Pour 1m bars : passer window_bars=390.

    Args:
        df : OHLCV indexed ts_event
        rvol_threshold : 0.3 default (consensus market-analyst)
        volume_col : nom colonne volume
        window_bars : window EMA pour mean volume reference

    Returns:
        df filtre (lignes rvol >= threshold conservees).
    """
    if volume_col not in df.columns:
        print(f"[labeler_v3] WARN : pas de colonne '{volume_col}', pre-filter skipped")
        return df

    vol_mean = df[volume_col].rolling(window_bars, min_periods=max(10, window_bars//4)).mean()
    rvol = df[volume_col] / vol_mean
    mask = rvol >= rvol_threshold
    n_dropped = (~mask).sum()
    n_total = len(df)
    print(f"[labeler_v3] RVOL pre-filter < {rvol_threshold} : "
          f"drop {n_dropped}/{n_total} ({n_dropped/n_total*100:.1f}%)")
    return df[mask].copy()


# ═════════════════════════════════════════════════════════════════════
# SAMPLE WEIGHT UNIQUENESS (Lopez AFML ch.4)
# ═════════════════════════════════════════════════════════════════════

def compute_concurrent_events(close_idx: pd.DatetimeIndex,
                                t1: pd.Series) -> pd.Series:
    """
    Lopez AFML ch.4.3 — pour chaque ts, count co-events actifs.

    co_events[t] = nb d'evenements actifs en t (chevauchement t1).

    Args:
        close_idx : DatetimeIndex de toutes les barres
        t1 : Series indexed entry_ts, valeur = ts barriere

    Returns:
        Series co_events count par ts.
    """
    out = pd.Series(0, index=close_idx, dtype=int)
    for entry_ts, t1_ts in t1.items():
        if pd.isna(t1_ts):
            continue
        if entry_ts not in close_idx or t1_ts not in close_idx:
            continue
        out.loc[entry_ts:t1_ts] += 1
    return out


def compute_sample_weights_uniqueness(events: pd.DataFrame,
                                        close_idx: pd.DatetimeIndex) -> pd.Series:
    """
    Lopez AFML ch.4.4 — Average uniqueness over event lifespan.

    sample_weight[i] = 1 / mean(1/co_events[t]) pour t in [entry_i, t1_i]

    Args:
        events : DataFrame indexed entry_ts avec colonne 't1' (= ts_t1_actual)
        close_idx : DatetimeIndex toutes les barres

    Returns:
        Series sample_weight indexed entry_ts (mean ~0.5 typique).
    """
    co_events = compute_concurrent_events(close_idx, events['ts_t1_actual'])
    weights = pd.Series(np.nan, index=events.index)
    for entry_ts, row in events.iterrows():
        t1_ts = row['ts_t1_actual']
        if pd.isna(t1_ts) or entry_ts not in close_idx:
            continue
        sub = co_events.loc[entry_ts:t1_ts]
        sub_safe = sub.replace(0, np.nan)
        weights.at[entry_ts] = 1.0 / (1.0 / sub_safe).mean() if sub_safe.notna().any() else 1.0
    return weights


# ═════════════════════════════════════════════════════════════════════
# PIPELINE PRINCIPAL
# ═════════════════════════════════════════════════════════════════════

def label_dataset_v3(df_ohlcv: pd.DataFrame,
                      tf_name: str = '5m',
                      pt_sl: tuple = (1.5, 1.0),
                      horizon_bars: int = 12,
                      rvol_threshold: float = 0.3,
                      vol_span: Optional[int] = None,
                      rvol_window_bars: Optional[int] = None,
                      vertical_label_mode: str = 'lopez_strict') -> pd.DataFrame:
    """
    Pipeline complet labeler v3 Lopez strict.

    Args:
        df_ohlcv : DataFrame OHLCV indexed ts_event (UTC, naive).
                   Colonnes : open, high, low, close, volume.
        tf_name : '1m', '5m', '15m', '1h' pour metadata
        pt_sl : (1.5, 1.0) = TP 1.5 vol, SL 1.0 vol → RR 1.5
        horizon_bars : 12 pour 5m = 1h. Adapter par TF.
        rvol_threshold : 0.3 (consensus 2 agents)
        vol_span : EWMA span pour daily_vol estimate (Lopez ch.3.1)
        rvol_window_bars : window mean volume reference. Default = horizon_bars × 6.

    Returns:
        DataFrame indexed ts_event avec colonnes :
            label {-1, 0, +1}, t1, barrier_type, daily_vol, sample_weight,
            tp_level, sl_level, return_at_t1
    """
    print(f"[labeler_v3] Pipeline labeling TF={tf_name} pt_sl={pt_sl} horizon={horizon_bars}")
    df = df_ohlcv.copy()
    if not isinstance(df.index, pd.DatetimeIndex):
        if 'ts_event' in df.columns:
            df = df.set_index('ts_event')
        else:
            raise ValueError("df_ohlcv must be indexed ts_event or have 'ts_event' col")

    # FIX RESERVE ml-trainer Q4.1 (02/05) :
    # Calculer daily_vol sur serie COMPLETE (pre-filter) pour eviter biais
    # EWMA span sur barres non-contigues. Puis filter, puis subset vol.
    # Sans ce fix : si pre-filter drop 30% bars 1m, span=390 devient ~1.4 jour reel.

    # 1. Daily volatility estimate sur serie complete (Lopez ch.3.1)
    if vol_span is None:
        vol_span = TF_SPANS.get(tf_name, 78)
    daily_vol_full = compute_daily_vol(df['close'], span=vol_span, tf=tf_name)
    print(f"[labeler_v3] daily_vol stats (pre-filter) : "
          f"mean={daily_vol_full.mean():.6f}, "
          f"median={daily_vol_full.median():.6f} (span={vol_span} for TF={tf_name})")

    # 2. Pre-filter RVOL (drop barres mortes)
    if rvol_window_bars is None:
        rvol_window_bars = horizon_bars * 6  # heuristique : 6 fois horizon
    df = filter_low_rvol(df, rvol_threshold, volume_col='volume',
                          window_bars=rvol_window_bars)
    if df.empty:
        return pd.DataFrame()

    # 3. Subset daily_vol sur barres survivantes (pas recalcul)
    daily_vol = daily_vol_full.reindex(df.index)

    # 3. Vertical barriers (horizon temporel)
    t1_vertical = compute_vertical_barriers(df['close'], num_bars=horizon_bars)

    # 4. Build events df
    events = pd.DataFrame({
        't1': t1_vertical,
        'daily_vol': daily_vol,
    }).dropna(subset=['daily_vol'])
    if events.empty:
        return pd.DataFrame()

    # 5. Apply triple barrier path detection (high/low intrabar)
    events_barriers = apply_triple_barrier(df, events, pt_sl=pt_sl)

    # 6. Get labels {-1, 0, +1} — Lopez ch.3.3 strict default
    events_labeled = get_labels(events_barriers,
                                  vertical_label_mode=vertical_label_mode)

    # 7. Sample weights uniqueness (Lopez ch.4)
    events_labeled['sample_weight'] = compute_sample_weights_uniqueness(
        events_labeled, df.index
    )

    # 8. Stats finales
    label_dist = events_labeled['label'].value_counts(normalize=True)
    print(f"[labeler_v3] Distribution labels :")
    print(f"  +1 (TP/long) : {label_dist.get(1, 0):.1%}")
    print(f"  -1 (SL/short): {label_dist.get(-1, 0):.1%}")
    print(f"  0  (HOLD)    : {label_dist.get(0, 0):.1%}")
    print(f"[labeler_v3] sample_weight mean={events_labeled['sample_weight'].mean():.3f}")

    return events_labeled


# ═════════════════════════════════════════════════════════════════════
# PURGED K-FOLD (Lopez AFML ch.7) — pour train_lightgbm.py dimanche
# ═════════════════════════════════════════════════════════════════════

def get_purged_train_test_indices(events: pd.DataFrame,
                                    n_splits: int = 12,
                                    embargo_bars: int = 12):
    """
    Lopez AFML ch.7.4.2 — Purged k-fold splits.

    Purge = remove from train les samples dont t1 chevauche test fold.
    Embargo = drop embargo_bars apres test fold (eviter leak via autocorr).

    Args:
        events : DataFrame indexed entry_ts avec colonne 'ts_t1_actual'
        n_splits : nb folds (default 12)
        embargo_bars : nb bars apres test a embargo (default = horizon_bars)

    Yields:
        (train_idx, test_idx) tuples comme sklearn KFold mais purged.
    """
    indices = events.index
    n_total = len(indices)
    fold_size = n_total // n_splits

    for fold_i in range(n_splits):
        test_start = fold_i * fold_size
        test_end = test_start + fold_size if fold_i < n_splits - 1 else n_total
        test_idx = indices[test_start:test_end]
        # Purge : drop train samples avec t1 dans test fold
        test_t_min = test_idx[0]
        test_t_max = test_idx[-1]
        # Embargo : drop embargo_bars apres test
        embargo_end_idx = min(test_end + embargo_bars, n_total)
        embargo_t_max = indices[embargo_end_idx - 1] if embargo_end_idx > 0 else test_t_max

        train_mask = pd.Series(True, index=indices)
        train_mask.loc[test_idx] = False
        # Drop samples train dont t1 chevauche [test_t_min, embargo_t_max]
        for entry_ts in indices:
            t1 = events.at[entry_ts, 'ts_t1_actual']
            if pd.isna(t1):
                continue
            if entry_ts <= embargo_t_max and t1 >= test_t_min:
                train_mask.at[entry_ts] = False
        train_idx = indices[train_mask]
        yield train_idx, test_idx


# ═════════════════════════════════════════════════════════════════════
# PREPARE FOR LIGHTGBM (drop HOLD + binarize) — Lopez ch.3.3 side-aware
# ═════════════════════════════════════════════════════════════════════

def prepare_for_lightgbm(events: pd.DataFrame,
                          target_side: str = 'buy') -> pd.DataFrame:
    """
    Convertit labels {-1, 0, +1} en binaire {0, 1} pour entrainement
    LightGBM par side (CLAUDE.md ML pipeline : 2 modeles par instrument).

    Drop HOLD (label=0) AVANT fit (recommandation ml-trainer).
    Sample weights normalises a sum=N pour Lopez ch.4.

    Args:
        events : output label_dataset_v3()
        target_side : 'buy' (label==+1 → 1) ou 'sell' (label==-1 → 1)

    Returns:
        DataFrame avec columns: y_binary, sample_weight (normalise),
        et drop label==0.
    """
    if target_side not in ('buy', 'sell'):
        raise ValueError("target_side must be 'buy' or 'sell'")

    out = events[events['label'] != 0].copy()  # drop HOLD
    if target_side == 'buy':
        out['y_binary'] = (out['label'] == 1).astype(int)
    else:
        out['y_binary'] = (out['label'] == -1).astype(int)

    # Normalisation sample_weight (Lopez : sum = N pour fit unbiased)
    sw = out['sample_weight'].fillna(1.0)
    out['sample_weight'] = sw * len(sw) / sw.sum()
    print(f"[labeler_v3] prepare_for_lightgbm({target_side}) : "
          f"N={len(out)} ({out['y_binary'].mean():.1%} positive class), "
          f"sw mean={out['sample_weight'].mean():.3f}")
    return out


# ═════════════════════════════════════════════════════════════════════
# CLI
# ═════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="NQ.c.0")
    parser.add_argument("--tf", default="5m", choices=["1m", "5m", "15m", "1h"])
    parser.add_argument("--start", default="2024-01-01")
    parser.add_argument("--end", default=None)
    parser.add_argument("--pt", type=float, default=1.5)
    parser.add_argument("--sl", type=float, default=1.0)
    parser.add_argument("--horizon", type=int, default=12)
    parser.add_argument("--output", default=None)
    args = parser.parse_args()
    print(f"[labeler_v3] CLI args: {vars(args)}")
    print("[labeler_v3] CLI smoke test : a connecter avec load_raw_*_databento samedi")
