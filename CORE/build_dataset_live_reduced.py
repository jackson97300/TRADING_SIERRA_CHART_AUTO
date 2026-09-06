"""build_dataset_live_reduced.py — Generateur CANONIQUE versionne du dataset ML
reduit, construit DEPUIS live_enriched (seule source de verite, 04/07/2026).

Remplace les scripts jetables de scratchpad (non reproductibles, cf audit
quality-auditor 04/07 "RESERVES : generateur non versionne = bloquant").

DECISIONS DE CONCEPTION (tracees) :
- SOURCE : DATA/live_enriched/sierra/{SYM}/*_sierra_enriched.jsonl (schema 3.7.22),
  PAS le backfill databento (gele + leak arr[sz-1] + PF backfill 2.32 -> 0.88 live).
- FEATURES : search space 113 de DOCS/features_finale_v1.txt (13 familles / 12 piliers,
  9 [STAR] winners), MOINS les DROP documentes ci-dessous, PLUS next_wall_dist_pct derive.
- LABEL : triple-barrier V5 (label_v5_dataset.py) MAIS avec atr_14m (TICKS), PAS atr.
  BUG CORRIGE (audit 04/07) : `atr` = ATR DAILY (~116t ES / ~764t NQ, DMP_Transform.h:1845
  f.atr=r.atr_daily) -> barrieres 40-190 points aberrantes. `atr_14m` (~8t ES / ~55t NQ,
  rolling 14, phase_b_rolling_inputs_streaming.py) = la bonne echelle pour un barrier 1-min
  horizon 60. label_v5_dataset.py:172 lit df["atr"] = MEME BUG a corriger en amont.
- ARCHITECTURE : 1 modele ES + 1 modele NQ SEPARES -> les fuites "instrument"
  (|meanES-meanNQ|>0.5) ne sont PAS un probleme (chaque modele ne voit qu'un instrument).
  On ne drope QUE : prix absolu (non-stationnaire), constantes (0 info), NaN total,
  features mortes documentees CLAUDE.md.

Usage : python -X utf8 CORE/build_dataset_live_reduced.py [--out DIR]
"""
from __future__ import annotations
import argparse, glob, json, os, re
from pathlib import Path

import numpy as np
import pandas as pd

# ── Parametres triple-barrier (identiques a label_v5_dataset.py, ATR corrige) ──
K_SL = 1.5           # SL = 1.5 x atr_14m (ticks)
K_TP_RATIO = 2.0     # TP = 2.0 x SL (R:R 2.0)
FORWARD_BARS = 60    # horizon 1h
TICK = 0.25          # ES et NQ
ATR_FIELD = "atr_14m"  # <-- FIX : PAS "atr" (daily)

ROOT = Path(__file__).resolve().parent.parent
FEATURES_DOC = ROOT / "DOCS" / "features_finale_v1.txt"

# ── Politique de DROP (documentee, audit 04/07) ──
DROP_FEATURES = {
    # Prix absolu (non-stationnaire, fuite garantie) — redondant avec dist_pvwap_*_pct
    "pvwap",
    # NaN 100% sur 18 sessions
    "session_id",              # bug encodage categoriel + redondant is_in_us_cash/ctx_session_phase
    "atr_regime_zscore_60d",   # z-score 60j : pas assez d'historique (18 sessions) — temporaire
    # Features MORTES documentees CLAUDE.md (Extension Lines desactivees ES)
    "long_dn_bar", "long_up_bar", "long_dn_up_pattern", "long_up_dn_pattern",
    # Quasi-constantes (>96% une seule valeur = 0 info)
    "day_type", "ib_broken_dn", "im_smt_divergence",
    "equal_highs_detected", "equal_lows_detected",
    "bn_absorb_ask", "bn_absorb_bid",   # rare-events <2% : revisiter en absorption x niveau plus tard
}

WALL_COLS = ["dist_mq_call_pct", "dist_mq_put_pct", "dist_mq_hvl_pct",
             "dist_gex_nearest_up_pct", "dist_gex_nearest_dn_pct"]


def parse_search_space(path: Path) -> list[str]:
    """Extrait les 113 noms de features de features_finale_v1.txt."""
    feats = []
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        name = s.split("#")[0].strip()
        if name and re.match(r"^[a-z0-9_]+$", name):
            feats.append(name)
    # dedup en preservant l'ordre
    return list(dict.fromkeys(feats))


def label_triple_barrier(df: pd.DataFrame) -> np.ndarray:
    """Triple-barrier V5 avec atr_14m. Retourne label in {-1,0,+1} par barre.
    Traite en INTRA-session (df = une seule session) -> pas de scan cross-day."""
    close = pd.to_numeric(df["price"], errors="coerce").to_numpy()
    high = pd.to_numeric(df.get("bar_high", df["price"]), errors="coerce").to_numpy()
    low = pd.to_numeric(df.get("bar_low", df["price"]), errors="coerce").to_numpy()
    atr = pd.to_numeric(df[ATR_FIELD], errors="coerce").to_numpy()
    n = len(df)
    lab = np.zeros(n, dtype=np.int8)
    for i in range(n - 1):
        a = atr[i]
        if not (a > 0):
            continue
        sl_t = K_SL * a
        tp_t = K_TP_RATIO * sl_t
        e = close[i]
        tp_long, sl_long = e + tp_t * TICK, e - sl_t * TICK
        tp_short, sl_short = e - tp_t * TICK, e + sl_t * TICK
        buy_win = sell_win = False
        buy_off = sell_off = FORWARD_BARS
        for k in range(1, FORWARD_BARS + 1):
            if i + k >= n:
                break
            if low[i + k] <= sl_long:
                buy_off = k
                break
            if high[i + k] >= tp_long:
                buy_win, buy_off = True, k
                break
        for k in range(1, FORWARD_BARS + 1):
            if i + k >= n:
                break
            if high[i + k] >= sl_short:
                sell_off = k
                break
            if low[i + k] <= tp_short:
                sell_win, sell_off = True, k
                break
        if buy_win and (not sell_win or buy_off < sell_off):
            lab[i] = 1
        elif sell_win and (not buy_win or sell_off < buy_off):
            lab[i] = -1
    return lab


def build_symbol(sym: str, kept: list[str]) -> tuple[pd.DataFrame, dict]:
    files = sorted(glob.glob(str(ROOT / f"DATA/live_enriched/sierra/{sym}/*_sierra_enriched.jsonl")))
    parts, dates = [], []
    for f in files:
        recs = [json.loads(x) for x in open(f, encoding="utf-8") if x.strip()]
        df = pd.DataFrame(recs)
        if "price" not in df or ATR_FIELD not in df or len(df) < 100:
            continue
        # DEDUP restart-replay (BUG enricher decouvert 04/07) : a chaque redemarrage
        # du service enricher, il RE-EMET toute la session depuis le debut (nouveau
        # boot_id) en append au meme JSONL -> jusqu'a 9-11 copies par barre, ts non
        # monotone, labeling triple-barrier corrompu (scan forward sur des replays).
        # keep='first' (ordre fichier = ordre append) = emission LIVE originale, evite
        # le recompute-avec-contexte-futur (famille arr[sz-1]). Verifie : dedup -> ts
        # strictement monotone, gap 60000ms, un seul boot_id. A CORRIGER a la source
        # (enricher : dedup a l'ecriture ou ne pas replay au restart).
        if "ts" in df.columns:
            df = df.drop_duplicates(subset="ts", keep="first").reset_index(drop=True)
        wc = [c for c in WALL_COLS if c in df.columns]
        if wc:
            df["next_wall_dist_pct"] = df[wc].apply(pd.to_numeric, errors="coerce").abs().min(axis=1)
        lab = label_triple_barrier(df)
        cols = [c for c in kept if c in df.columns]
        out = df[cols].apply(pd.to_numeric, errors="coerce")
        out["label"] = lab
        out["session_date"] = df.get("session_date_trading", df.get("session_date", os.path.basename(f)[:8]))
        out["ts"] = pd.to_numeric(df.get("ts", pd.Series(range(len(df)))), errors="coerce")
        parts.append(out)
        dates.append(os.path.basename(f)[:8])
    D = pd.concat(parts, ignore_index=True).sort_values("ts").reset_index(drop=True)
    meta = {
        "symbol": sym, "n_bars": int(len(D)), "n_sessions": len(dates),
        "sessions": dates, "n_features": len([c for c in kept if c in D.columns]),
        "label_buy": int((D["label"] == 1).sum()),
        "label_sell": int((D["label"] == -1).sum()),
        "label_hold": int((D["label"] == 0).sum()),
    }
    return D, meta


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "DATA" / "DATASETS"))
    args = ap.parse_args()
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    search = parse_search_space(FEATURES_DOC)
    kept = [f for f in search if f not in DROP_FEATURES] + ["next_wall_dist_pct"]
    kept = list(dict.fromkeys(kept))

    provenance = {
        "generator": "CORE/build_dataset_live_reduced.py",
        "source": "DATA/live_enriched/sierra/{SYM}/*.jsonl (schema 3.7.22)",
        "atr_field": ATR_FIELD, "K_SL": K_SL, "K_TP_RATIO": K_TP_RATIO,
        "forward_bars": FORWARD_BARS, "tick": TICK,
        "search_space": len(search), "dropped": sorted(DROP_FEATURES),
        "n_kept_features": len(kept), "kept_features": kept,
        "symbols": {},
    }
    for sym in ("ES", "NQ"):
        D, meta = build_symbol(sym, kept)
        p = out_dir / f"{sym}_dataset_live_reduced.parquet"
        D.to_parquet(p)
        provenance["symbols"][sym] = meta
        b, s, h = meta["label_buy"], meta["label_sell"], meta["label_hold"]
        print(f"{sym}: {meta['n_bars']} barres | {meta['n_features']} features | "
              f"BUY={b} SELL={s} HOLD={h} ({100*b/(b+s):.0f}% BUY sur trades) | "
              f"{meta['n_sessions']} sessions -> {p.name}")
    prov_path = out_dir / "dataset_live_reduced_provenance.json"
    prov_path.write_text(json.dumps(provenance, indent=2), encoding="utf-8")
    print(f"\nfeatures conservees : {len(kept)} (search 113 - {len(DROP_FEATURES)} drop + 1 derive)")
    print(f"provenance -> {prov_path}")


if __name__ == "__main__":
    main()
