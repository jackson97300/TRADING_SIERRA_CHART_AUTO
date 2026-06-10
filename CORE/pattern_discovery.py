"""
Pattern Discovery Scanner (18/04/2026)

Approche INVERSE du rule-based : au lieu de coder des strategies a priori,
on scanne TOUTES les combinaisons de features binaires et on laisse les
donnees reveler ce qui a VRAIMENT marche.

Methodologie :
  1. Pre-compute : pour chaque barre, simuler LONG + SHORT bracket (SL/TP)
     -> outcome_long[t], outcome_short[t] avec R multiplier (+RR, -1, ou timeout)
  2. Pour chaque feature binaire : subset = barres ou feature=1, stats agregees
  3. Pour chaque PAIRE de features : stats agregees
  4. Triplets : seulement pour les paires les plus prometteuses (n>=50, PF>=1.2)
  5. Avec condition directionnelle niveau : near support -> LONG, near resist -> SHORT
  6. Ranking : top 30 par (PF * sqrt(n) / 10) = score combinant edge et robustesse

Output : CSV + rapport markdown avec les patterns qui ont un vrai edge empirique.

Jackson's insight clef : le setup gagnant peut etre CONTRARIAN
  (trend UP + accumulation patterns DOWN + niveau + rejet = SHORT winner).
Donc on teste BUY et SELL sur chaque pattern, pas d'a priori directionnel.

USAGE :
    python -X utf8 CORE/pattern_discovery.py
    python -X utf8 CORE/pattern_discovery.py --symbol NQ --top 30
"""

from __future__ import annotations

import json
import sys
from itertools import combinations
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from rolling_features import RollingFeatures  # noqa: E402

DATA_ROOT = Path("DATA")
OUTPUT_DIR = Path("DATA/PATTERN_DISCOVERY")
TICK_SIZE = 0.25
SLIPPAGE_R = 0.1
RTH_START_MIN = 9 * 60 + 30
RTH_END_MIN = 16 * 60

# Features binaires event-based a scanner (color/rotation EXCLUES car cassees pre-3.7.6)
BINARY_FEATURES = [
    "bn_absorb_bid", "bn_absorb_ask",
    "bn_long_up", "bn_long_dn",
    "bar_long_up_bar", "bar_long_dn_bar",
    "bar_long_dn_up", "bar_long_up_dn",   # reversals rares
    "bn_volume_up", "bn_volume_dn",
    "fp_edge_buy", "fp_edge_sell",
    "bar_edge_buy", "bar_edge_sell",
    "new_swing_high", "new_swing_low",
    "rvol_buy", "rvol_sell",
    "rvol_absorb_buy", "rvol_absorb_sell",
    "ib_broken_up", "ib_broken_down",
    "ib_complete",
    "is_double_dist",
    "bool_above_vwap_d", "bool_above_cur_vpoc",
    "bool_above_mq_call", "bool_above_mq_hvl",
    "bool_gex_flip_zone",
    "inside_cur_va", "inside_prev_va",
    "vix_above_hvl_0dte",
]

# Features directionnelles (= conditions de contexte a combiner)
CONTEXT_CONDITIONS = {
    "near_support_10t": lambda df: _near_support(df, 10),
    "near_resist_10t":  lambda df: _near_resistance(df, 10),
    "near_support_20t": lambda df: _near_support(df, 20),
    "near_resist_20t":  lambda df: _near_resistance(df, 20),
    "trend_up":         lambda df: _trend_filter(df, +1),
    "trend_dn":         lambda df: _trend_filter(df, -1),
    "rvol_high":        lambda df: _num(df, "rvol") >= 1.5,
    "rvol_extreme":     lambda df: _num(df, "rvol_zscore") >= 2.0,
    "morning_us":       lambda df: _hour_range(df, 9, 11),
}


def _num(df: pd.DataFrame, col: str, default: float = 0.0) -> pd.Series:
    if col not in df.columns:
        return pd.Series(default, index=df.index)
    return pd.to_numeric(df[col], errors="coerce").fillna(default)


def _near_support(df: pd.DataFrame, thr: float) -> pd.Series:
    cols = ["dist_mq_put", "dist_mq_hvl", "dist_gex_nearest_dn",
            "dist_swing_low", "dist_cur_val"]
    mask = pd.Series(False, index=df.index)
    for c in cols:
        if c in df.columns:
            v = _num(df, c, 999)
            mask |= (v >= -thr) & (v < 0)
    return mask


def _near_resistance(df: pd.DataFrame, thr: float) -> pd.Series:
    cols = ["dist_mq_call", "dist_gex_nearest_up", "dist_swing_high",
            "dist_cur_vah"]
    mask = pd.Series(False, index=df.index)
    for c in cols:
        if c in df.columns:
            v = _num(df, c, 0)
            mask |= (v > 0) & (v <= thr)
    return mask


def _trend_filter(df: pd.DataFrame, direction: int) -> pd.Series:
    """Trend confirme via cvd_day_dir + vwap_ma_align (PAS ma_trend casse)."""
    cvd = _num(df, "cvd_day_dir").astype(int)
    vwap = _num(df, "vwap_ma_align").astype(int)
    return (cvd == direction) & (vwap == direction)


def _hour_range(df: pd.DataFrame, h_start: int, h_end: int) -> pd.Series:
    if "ts" not in df.columns:
        return pd.Series(False, index=df.index)
    ts_utc = pd.to_datetime(pd.to_numeric(df["ts"], errors="coerce"),
                            unit="ms", utc=True, errors="coerce")
    hour_et = ts_utc.dt.tz_convert("America/New_York").dt.hour
    return (hour_et >= h_start) & (hour_et <= h_end)


def load_jsonl_dir(symbol: str) -> pd.DataFrame:
    rows = []
    for f in sorted((DATA_ROOT / symbol).glob("*.jsonl")):
        for line in f.read_text(encoding="utf-8").splitlines():
            s = line.strip()
            if not s:
                continue
            try:
                rows.append(json.loads(s))
            except json.JSONDecodeError:
                continue
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    if "ts" in df.columns:
        df["ts"] = pd.to_numeric(df["ts"], errors="coerce")
        df = df.sort_values("ts").reset_index(drop=True)
    for col in ["price", "bar_high", "bar_low", "atr"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def is_rth_mask(df: pd.DataFrame) -> np.ndarray:
    """Mask booleen : True si barre en session US RTH."""
    if "ts" not in df.columns:
        return np.ones(len(df), dtype=bool)
    ts_utc = pd.to_datetime(pd.to_numeric(df["ts"], errors="coerce"),
                            unit="ms", utc=True, errors="coerce")
    ts_et = ts_utc.dt.tz_convert("America/New_York")
    minutes_et = ts_et.dt.hour * 60 + ts_et.dt.minute
    return ((minutes_et >= RTH_START_MIN) & (minutes_et < RTH_END_MIN)).to_numpy()


def precompute_outcomes(df: pd.DataFrame, sl_ticks: float, rr: float,
                        max_bars: int, apply_slip: bool = True) -> tuple:
    """Pre-compute outcome LONG et SHORT pour chaque barre.

    Retourne (r_long, r_short) : arrays de R multipliers.
    SL gagne sur TP dans meme barre (pessimiste).
    """
    n = len(df)
    price = df["price"].to_numpy()
    bh = df["bar_high"].to_numpy()
    bl = df["bar_low"].to_numpy()

    r_long = np.full(n, np.nan, dtype=np.float64)
    r_short = np.full(n, np.nan, dtype=np.float64)

    sl_pts = sl_ticks * TICK_SIZE
    tp_ticks = sl_ticks * rr
    tp_pts = tp_ticks * TICK_SIZE

    for t in range(n):
        entry = price[t]
        if not np.isfinite(entry):
            continue
        end_idx = min(t + 1 + max_bars, n)
        # LONG
        sl_px = entry - sl_pts
        tp_px = entry + tp_pts
        outcome_long = None
        for i in range(t + 1, end_idx):
            bh_i, bl_i = bh[i], bl[i]
            if not (np.isfinite(bh_i) and np.isfinite(bl_i)):
                continue
            if bl_i <= sl_px:
                outcome_long = -1.0
                break
            if bh_i >= tp_px:
                outcome_long = rr
                break
        if outcome_long is None and end_idx > t + 1:
            final = price[end_idx - 1]
            if np.isfinite(final):
                outcome_long = (final - entry) / sl_pts
        r_long[t] = outcome_long if outcome_long is not None else np.nan
        # SHORT
        sl_px = entry + sl_pts
        tp_px = entry - tp_pts
        outcome_short = None
        for i in range(t + 1, end_idx):
            bh_i, bl_i = bh[i], bl[i]
            if not (np.isfinite(bh_i) and np.isfinite(bl_i)):
                continue
            if bh_i >= sl_px:
                outcome_short = -1.0
                break
            if bl_i <= tp_px:
                outcome_short = rr
                break
        if outcome_short is None and end_idx > t + 1:
            final = price[end_idx - 1]
            if np.isfinite(final):
                outcome_short = (entry - final) / sl_pts
        r_short[t] = outcome_short if outcome_short is not None else np.nan

    if apply_slip:
        r_long -= SLIPPAGE_R
        r_short -= SLIPPAGE_R

    return r_long, r_short


def stats_for_mask(r: np.ndarray, mask: np.ndarray) -> dict:
    """Calcule stats pour subset de trades."""
    sel = r[mask & ~np.isnan(r)]
    n = len(sel)
    if n == 0:
        return {"n": 0, "wr": 0.0, "pf": 0.0, "ev": 0.0, "totR": 0.0}
    wins = sel[sel > 0]
    losses = sel[sel < 0]
    total_win = wins.sum() if len(wins) else 0.0
    total_loss = -losses.sum() if len(losses) else 0.0
    pf = float(total_win / total_loss) if total_loss > 0 else (np.inf if total_win > 0 else 0.0)
    return {
        "n": int(n),
        "wr": float(len(wins) / n),
        "pf": pf,
        "ev": float(sel.mean()),
        "totR": float(sel.sum()),
    }


def scan_features(df: pd.DataFrame, r_long: np.ndarray, r_short: np.ndarray,
                   features: list[str], rth_mask: np.ndarray,
                   context_masks: dict) -> pd.DataFrame:
    """Scan toutes les features + combinaisons avec contextes."""
    results = []
    # Pre-compute feature masks (binary)
    feat_masks = {}
    for f in features:
        if f in df.columns:
            v = pd.to_numeric(df[f], errors="coerce").fillna(0).astype(int).to_numpy()
            feat_masks[f] = (v == 1) & rth_mask

    # --- SINGLE FEATURES ---
    for f, m in feat_masks.items():
        for direction, r in [("LONG", r_long), ("SHORT", r_short)]:
            s = stats_for_mask(r, m)
            if s["n"] >= 30 and s["pf"] >= 1.1:
                results.append({
                    "pattern": f,
                    "direction": direction,
                    "context": "none",
                    **s,
                })

    # --- SINGLE + CONTEXT ---
    for f, m in feat_masks.items():
        for ctx_name, ctx_mask in context_masks.items():
            combined = m & ctx_mask.to_numpy()
            for direction, r in [("LONG", r_long), ("SHORT", r_short)]:
                s = stats_for_mask(r, combined)
                if s["n"] >= 30 and s["pf"] >= 1.2:
                    results.append({
                        "pattern": f,
                        "direction": direction,
                        "context": ctx_name,
                        **s,
                    })

    # --- PAIRS ---
    feat_list = list(feat_masks.keys())
    for f1, f2 in combinations(feat_list, 2):
        combined = feat_masks[f1] & feat_masks[f2]
        if combined.sum() < 20:
            continue  # skip pairs trop rares
        for direction, r in [("LONG", r_long), ("SHORT", r_short)]:
            s = stats_for_mask(r, combined)
            if s["n"] >= 30 and s["pf"] >= 1.3:
                results.append({
                    "pattern": f"{f1} + {f2}",
                    "direction": direction,
                    "context": "none",
                    **s,
                })

    # --- PAIRS + NIVEAU DIRECTIONNEL ---
    # Pour chaque paire, ajouter near_support (pour LONG) ou near_resist (pour SHORT)
    near_sup_10 = context_masks["near_support_10t"].to_numpy()
    near_res_10 = context_masks["near_resist_10t"].to_numpy()
    for f1, f2 in combinations(feat_list, 2):
        pair_mask = feat_masks[f1] & feat_masks[f2]
        if pair_mask.sum() < 15:
            continue
        # LONG sur support
        combined_long = pair_mask & near_sup_10
        s = stats_for_mask(r_long, combined_long)
        if s["n"] >= 30 and s["pf"] >= 1.3:
            results.append({
                "pattern": f"{f1} + {f2}",
                "direction": "LONG",
                "context": "near_support_10t",
                **s,
            })
        # SHORT sur resistance
        combined_short = pair_mask & near_res_10
        s = stats_for_mask(r_short, combined_short)
        if s["n"] >= 30 and s["pf"] >= 1.3:
            results.append({
                "pattern": f"{f1} + {f2}",
                "direction": "SHORT",
                "context": "near_resist_10t",
                **s,
            })

    return pd.DataFrame(results)


def rank_patterns(df_results: pd.DataFrame, top_k: int = 30) -> pd.DataFrame:
    """Score combinant edge (PF) et robustesse (n)."""
    if df_results.empty:
        return df_results
    df = df_results.copy()
    # Score = PF * sqrt(n / 100) * EV_positive_bonus
    # Favor PF eleve ET n suffisant ET EV positif
    df["score"] = (
        df["pf"].clip(upper=3.0)
        * np.sqrt(df["n"] / 100.0).clip(upper=2.0)
        * df["ev"].clip(lower=-0.5)
    )
    return df.sort_values("score", ascending=False).head(top_k)


def main():
    top_k = 30
    symbols = ["ES", "NQ"]
    if "--symbol" in sys.argv:
        idx = sys.argv.index("--symbol")
        if idx + 1 < len(sys.argv):
            symbols = [sys.argv[idx + 1]]
    if "--top" in sys.argv:
        idx = sys.argv.index("--top")
        if idx + 1 < len(sys.argv):
            top_k = int(sys.argv[idx + 1])

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print("=" * 95)
    print(f"  PATTERN DISCOVERY SCANNER — {len(BINARY_FEATURES)} features, "
          f"{len(CONTEXT_CONDITIONS)} contextes")
    print(f"  Bracket : SL adaptatif par symbole, RR 2.0, max 40 bars, "
          f"slippage -0.1R, RTH only")
    print("=" * 95)

    for symbol in symbols:
        print(f"\n[{symbol}] Loading...")
        df = load_jsonl_dir(symbol)
        if df.empty:
            print(f"[{symbol}] EMPTY")
            continue
        print(f"[{symbol}] Computing rolling features ({len(df)} bars)...")
        df = RollingFeatures().compute(df)
        rth = is_rth_mask(df)
        rth_bars = rth.sum()
        print(f"[{symbol}] RTH bars: {rth_bars}")

        # SL adaptatif par symbole
        sl_ticks = 15.0 if symbol == "ES" else 25.0
        print(f"[{symbol}] Pre-computing outcomes (SL={sl_ticks}t, RR=2.0)...")
        r_long, r_short = precompute_outcomes(df, sl_ticks, 2.0, 40)

        # Stats bracketes de base
        n_long_valid = np.sum(~np.isnan(r_long))
        n_short_valid = np.sum(~np.isnan(r_short))
        print(f"[{symbol}] Trades simules : LONG={n_long_valid}, SHORT={n_short_valid}")
        base_long = stats_for_mask(r_long, rth)
        base_short = stats_for_mask(r_short, rth)
        print(f"[{symbol}] Baseline ALL LONG  : n={base_long['n']} WR={base_long['wr']:.1%} "
              f"PF={base_long['pf']:.2f}")
        print(f"[{symbol}] Baseline ALL SHORT : n={base_short['n']} WR={base_short['wr']:.1%} "
              f"PF={base_short['pf']:.2f}")

        # Context masks
        context_masks = {k: v(df) for k, v in CONTEXT_CONDITIONS.items()}

        print(f"[{symbol}] Scanning patterns...")
        results = scan_features(df, r_long, r_short, BINARY_FEATURES, rth,
                                 context_masks)
        if results.empty:
            print(f"[{symbol}] Aucun pattern trouve avec stats minimales")
            continue

        print(f"[{symbol}] {len(results)} patterns scannes avec n>=30 et PF>=1.1")

        ranked = rank_patterns(results, top_k=top_k)
        out_csv = OUTPUT_DIR / f"{symbol}_patterns_ranked.csv"
        ranked.to_csv(out_csv, index=False)
        print(f"[{symbol}] CSV: {out_csv}")

        # Affichage top
        print(f"\n  ╔════════ TOP {top_k} PATTERNS {symbol} ════════╗")
        print(f"  {'Rank':4s} {'Pattern':55s} {'Dir':6s} {'Context':22s} "
              f"{'n':5s} {'WR':6s} {'PF':6s} {'EV':7s} {'totR':7s} {'score':6s}")
        for i, r in ranked.head(top_k).iterrows():
            pf_str = f"{r['pf']:.2f}" if np.isfinite(r['pf']) else "inf"
            pattern = r['pattern'][:55]
            print(f"  {ranked.index.get_loc(i)+1:3d}. {pattern:55s} "
                  f"{r['direction']:6s} {r['context']:22s} "
                  f"n={r['n']:4d} {r['wr']:5.1%} {pf_str:>5s} "
                  f"{r['ev']:+.2f} {r['totR']:+6.1f} {r['score']:.2f}")

    print()


if __name__ == "__main__":
    main()
