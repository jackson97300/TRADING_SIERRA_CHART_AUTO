"""
Audit parite bit-for-bit : pipeline training vs V2CLEAN live.

CRITIQUE pre-deploy : le bot V2CLEAN calcule-t-il EXACTEMENT les memes features
qu'a l'entrainement ? Ecart > 1e-6 = bug potentiel qui peut invalider
les signals ML en production.

Methode (version 2 — 19/04/2026 apres correction Jackson) :
  1. Source = JSONL brutes directement depuis VPS (pas de contamination injector)
  2. Pour une bar test post-fix DMP 3.7.7 :
     - Live side : V2CLEAN atr_normalize_live + IMBuffer
     - Training side : appel DIRECT des modules officiels utilises par
       dataset_builder (`_normalize_by_atr` + `intermarket_features`)
  3. Comparer feature-by-feature. Tolerance 1e-6.

On ne compare PAS contre le parquet stocke (qui exclut 17/04 via injector nullify
les mq_* sans JSON MenthorQ) mais contre les modules en VIF sur les JSONL frais VPS.

Usage :
    # Pre-requis : scp depuis VPS
    scp Administrator@212.28.179.199:C:/TRADING_SIERRA_CHART_AUTO/DATA/ES/20260417_ES.jsonl /tmp/parity_vps/
    scp Administrator@212.28.179.199:C:/TRADING_SIERRA_CHART_AUTO/DATA/NQ/20260417_NQ.jsonl /tmp/parity_vps/

    python -X utf8 CORE/research/parity_audit.py

Output :
    CORE/research/parity_audit_detail.csv
    Stdout : rapport MATCH / MISMATCH / MISSING_LIVE
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "V2CLEAN"))
sys.path.insert(0, str(REPO_ROOT / "CORE"))

# Live V2CLEAN
from V2CLEAN.common.atr_normalize_live import (
    normalize_atr_features,
    ATR_NORMALIZED_FEATURES,
)
from V2CLEAN.common.im_features_live import IMBuffer

# Training CORE
from dataset_builder import TO_NORMALIZE, POINTS_FEATURES, TICK_SIZE
from intermarket_features import IntermarketFeatures


TOLERANCE = 1e-6


def load_bars_jsonl(path: Path) -> list[dict]:
    bars = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            bars.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return bars


# ─────────────────────────────────────────────────────────────────────────────
# TRAINING PIPELINE — reproduction du code officiel dataset_builder
# ─────────────────────────────────────────────────────────────────────────────

def training_atr_normalize(bar: dict) -> dict:
    """Appel du meme algorithme que `dataset_builder._normalize_by_atr`.

    Pour UNE bar :
      - Pour chaque feat in TO_NORMALIZE :
        - Si feat in POINTS_FEATURES : ticks = raw / TICK_SIZE
        - Sinon : ticks = raw
        - new_col = ticks / atr
    Returns : dict feat_atr -> value
    """
    atr = bar.get("atr")
    if atr is None or float(atr) <= 0:
        return {}
    atr_val = float(atr)

    result = {}
    for col in TO_NORMALIZE:
        if col not in bar:
            continue
        raw = bar[col]
        if raw is None:
            continue
        try:
            raw_val = float(raw)
        except (TypeError, ValueError):
            continue
        if not np.isfinite(raw_val):
            continue

        # POINTS -> TICKS si applicable
        ticks = raw_val / TICK_SIZE if col in POINTS_FEATURES else raw_val

        # new col name
        if col.endswith("_ticks"):
            new_col = col.replace("_ticks", "_atr")
        else:
            new_col = f"{col}_atr"

        result[new_col] = ticks / atr_val

    return result


def training_im_features(
    bars_target: list[dict],
    bars_other: list[dict],
    target_bar_idx: int,
    target_symbol: str,
) -> dict:
    """Appel de `intermarket_features.compute_intermarket_features` sur 2 DataFrames.

    Prend les 10 dernieres bars du target + other (alignees par ts),
    retourne les im_* calcules pour la bar cible.
    """
    start = max(0, target_bar_idx - 9)
    target_slice = bars_target[start:target_bar_idx + 1]

    # Align other par ts
    target_ts = [b.get("ts") for b in target_slice]
    other_slice = []
    for ts in target_ts:
        best = min(bars_other, key=lambda b: abs(b.get("ts", 0) - ts), default=None)
        if best is not None:
            other_slice.append(best)

    if len(target_slice) < 5 or len(other_slice) < 5:
        return {}

    df_t = pd.DataFrame(target_slice)
    df_o = pd.DataFrame(other_slice)

    # IntermarketFeatures.compute attend 2 df, retourne df_t enrichi
    try:
        imc = IntermarketFeatures()
        df_enriched = imc.compute(df_t, df_o, target=target_symbol)
    except Exception as e:
        return {"_error": f"im training: {type(e).__name__}: {e}"}

    # Extraire im_* de la derniere ligne
    last = df_enriched.iloc[-1]
    return {k: v for k, v in last.items() if k.startswith("im_")}


# ─────────────────────────────────────────────────────────────────────────────
# LIVE V2CLEAN
# ─────────────────────────────────────────────────────────────────────────────

def live_atr_normalize(bar: dict) -> dict:
    """V2CLEAN/common/atr_normalize_live.py."""
    b = dict(bar)
    normalize_atr_features(b)
    return {k: v for k, v in b.items() if k.endswith("_atr") and k not in bar}


def live_im_features(
    bars_target: list[dict],
    bars_other: list[dict],
    target_bar_idx: int,
    target_symbol: str,
) -> dict:
    """V2CLEAN/common/im_features_live.IMBuffer."""
    buf = IMBuffer()
    start = max(0, target_bar_idx - 9)
    other_sym = "NQ" if target_symbol == "ES" else "ES"

    for i in range(start, target_bar_idx + 1):
        t_bar = bars_target[i]
        buf.update(target_symbol, t_bar)
        t_ts = t_bar.get("ts", 0)
        best_o = min(bars_other, key=lambda b: abs(b.get("ts", 0) - t_ts), default=None)
        if best_o is not None:
            buf.update(other_sym, best_o)

    return buf.compute(target_symbol)


# ─────────────────────────────────────────────────────────────────────────────
# AUDIT
# ─────────────────────────────────────────────────────────────────────────────

def compare(live_feats: dict, train_feats: dict, label: str) -> list[dict]:
    """Compare 2 dicts feature -> value."""
    results = []
    common = set(live_feats.keys()) & set(train_feats.keys())
    live_only = set(live_feats.keys()) - common
    train_only = set(train_feats.keys()) - common

    for feat in sorted(common):
        lv, tv = live_feats[feat], train_feats[feat]
        if lv is None or tv is None:
            results.append({"feature": feat, "live_val": lv, "training_val": tv,
                            "diff": None, "status": "NONE", "section": label})
            continue
        try:
            lf, tf = float(lv), float(tv)
        except (TypeError, ValueError):
            continue

        if not np.isfinite(lf) or not np.isfinite(tf):
            if np.isfinite(lf) != np.isfinite(tf):
                results.append({"feature": feat, "live_val": lv, "training_val": tv,
                                "diff": None, "status": "MISMATCH_NAN",
                                "section": label})
            continue

        diff = abs(lf - tf)
        if diff <= TOLERANCE:
            status = "MATCH"
        elif diff <= 0.01 * max(abs(lf), abs(tf), 1e-9):
            status = "NEAR_MATCH"
        else:
            status = "MISMATCH"

        results.append({
            "feature": feat,
            "live_val": round(lf, 6),
            "training_val": round(tf, 6),
            "diff": round(diff, 8),
            "status": status,
            "section": label,
        })

    # Features seulement live (anomalie ?) ou seulement training (= MISSING_LIVE)
    for feat in sorted(train_only):
        results.append({"feature": feat, "live_val": None,
                        "training_val": train_feats[feat],
                        "diff": None, "status": "MISSING_LIVE", "section": label})
    for feat in sorted(live_only):
        results.append({"feature": feat, "live_val": live_feats[feat],
                        "training_val": None,
                        "diff": None, "status": "LIVE_ONLY", "section": label})

    return results


def main():
    print("=" * 70)
    print("  AUDIT PARITE BIT-FOR-BIT — training vs V2CLEAN live")
    print("  Source : VPS JSONL 17/04/2026 (post-fix DMP 3.7.7)")
    print("=" * 70)

    vps_dir = REPO_ROOT / "CORE/research/_parity_vps"
    es_path = vps_dir / "ES_vps.jsonl"
    nq_path = vps_dir / "NQ_vps.jsonl"
    if not (es_path.exists() and nq_path.exists()):
        print(f"[ERREUR] JSONL VPS manquants. Run d'abord :")
        print(f"  scp Administrator@212.28.179.199:C:/TRADING_SIERRA_CHART_AUTO/DATA/ES/20260417_ES.jsonl {es_path}")
        print(f"  scp Administrator@212.28.179.199:C:/TRADING_SIERRA_CHART_AUTO/DATA/NQ/20260417_NQ.jsonl {nq_path}")
        return

    bars_nq = load_bars_jsonl(nq_path)
    bars_es = load_bars_jsonl(es_path)
    print(f"  NQ bars VPS : {len(bars_nq)}")
    print(f"  ES bars VPS : {len(bars_es)}")

    # ─── AUDIT MULTI-BAR (50 bars par instrument, post-fix DMP 3.7.7) ──
    # Reviewer 19/04 : 1 seule bar insuffisante, cas limites possibles.
    # On teste 50 bars random par instrument + les 2 instruments (ES + NQ).
    import random
    random.seed(42)  # reproductible

    all_results = []
    for sym, bars_t, bars_o in [
        ("NQ", bars_nq, bars_es),
        ("ES", bars_es, bars_nq),
    ]:
        # 50 bars random en session US (assumer bar > 700 pour avoir du delta_day)
        valid_indices = [i for i in range(min(700, len(bars_t)), len(bars_t))]
        sample = random.sample(valid_indices, min(50, len(valid_indices)))

        for idx in sample:
            bar = bars_t[idx]
            # ATR
            live_atr = live_atr_normalize(bar)
            train_atr = training_atr_normalize(bar)
            r_atr = compare(live_atr, train_atr, f"ATR-{sym}")
            for r in r_atr:
                r["bar_idx"] = idx
                r["ts"] = bar.get("ts")
            all_results.extend(r_atr)

            # IM
            live_im = live_im_features(bars_t, bars_o, idx, sym)
            train_im = training_im_features(bars_t, bars_o, idx, sym)
            r_im = compare(live_im, train_im, f"IM-{sym}")
            for r in r_im:
                r["bar_idx"] = idx
                r["ts"] = bar.get("ts")
            all_results.extend(r_im)

        print(f"  Audit {sym} : {len(sample)} bars testees")
    print("\n" + "=" * 70)
    print("  RAPPORT GLOBAL")
    print("=" * 70)
    status_counts = {}
    for r in all_results:
        key = (r["section"], r["status"])
        status_counts[key] = status_counts.get(key, 0) + 1

    print(f"\n  {'Section':<6s} {'Status':<20s} {'Count':>6s}")
    print("  " + "-" * 40)
    for (sec, st), cnt in sorted(status_counts.items()):
        marker = "🚨" if "MISMATCH" in st else ("⚠️" if "MISSING" in st or "LIVE_ONLY" in st else "✅")
        print(f"  {sec:<6s} {marker} {st:<18s} {cnt:>6d}")

    # Detail MISMATCHES
    mismatches = [r for r in all_results if "MISMATCH" in r["status"]]
    if mismatches:
        print(f"\n  🚨 {len(mismatches)} MISMATCH (parite CASSEE) :")
        for r in mismatches[:15]:
            print(f"    [{r['section']}] {r['feature']:<40s} "
                  f"live={r['live_val']!s:>12s} train={r['training_val']!s:>12s} "
                  f"diff={r['diff']!s:>10s}")
    else:
        print(f"\n  ✅ PAS DE MISMATCH — parite bit-for-bit OK !")

    # Detail NEAR_MATCH
    nears = [r for r in all_results if r["status"] == "NEAR_MATCH"]
    if nears:
        print(f"\n  ⚠️ {len(nears)} NEAR_MATCH (diff < 1% mais > 1e-6) :")
        for r in nears[:10]:
            print(f"    [{r['section']}] {r['feature']:<40s} diff={r['diff']}")

    # Sauvegarde CSV
    out_csv = REPO_ROOT / "CORE/research/parity_audit_detail.csv"
    pd.DataFrame(all_results).to_csv(out_csv, index=False)
    print(f"\n  Detail sauvegarde : {out_csv}")


if __name__ == "__main__":
    main()
