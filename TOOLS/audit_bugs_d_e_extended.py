"""Audit étendu Bug D (signes incohérents) + Bug E (cap ATR sature).

Analyse TOUTES les bars JSONL post-fix BUG #3 (trades_window_aligned=1)
sur ES/NQ/MGC pour valider empiriquement :
1. Bug D : distribution signes raw vs pct vs atr sur 22+ niveaux
2. Bug E : % bars où dist_*_atr clamped à ±5
"""
import json
from pathlib import Path
from collections import defaultdict

ROOT = Path("d:/TRADING_SIERRA_CHART_AUTO")

# Niveaux et leurs 3 variantes (raw, pct, atr)
LEVELS = [
    ("ib_high", "dist_ib_high", "dist_ib_high_pct", "dist_ib_high_atr"),
    ("ib_low", "dist_ib_low", "dist_ib_low_pct", "dist_ib_low_atr"),
    ("sess_high", "dist_sess_high", "dist_sess_high_pct", "dist_sess_high_atr"),
    ("sess_low", "dist_sess_low", "dist_sess_low_pct", "dist_sess_low_atr"),
    ("cur_vpoc", "dist_cur_vpoc", "dist_cur_vpoc_pct", "dist_cur_vpoc_atr"),
    ("cur_vah", "dist_cur_vah", "dist_cur_vah_pct", "dist_cur_vah_atr"),
    ("cur_val", "dist_cur_val", "dist_cur_val_pct", "dist_cur_val_atr"),
    # prev_* et pdh/pdl n'ont pas de raw "dist_X" - skip
    # mq_call/put/hvl pas de raw
]


def analyze_file(path: Path, sym_label: str):
    if not path.exists():
        print(f"{sym_label}: file missing")
        return None
    bars = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                bars.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    # Filter only bars aligned=1 (post fix BUG #3)
    aligned = [b for b in bars if b.get("trades_window_aligned") == 1]
    print(f"\n{'='*80}")
    print(f"=== {sym_label} : total {len(bars)} bars, aligned={len(aligned)} ===")
    print(f"{'='*80}")
    if not aligned:
        return None

    # Bug D : verifier coherence signes pour CHAQUE niveau
    print(f"\n--- BUG D : Coherence signes raw vs pct vs atr (sur {len(aligned)} bars aligned) ---")
    for lvl_name, raw_key, pct_key, atr_key in LEVELS:
        signs = {"raw_neg_pct_pos": 0, "raw_pos_pct_neg": 0, "raw_neg_atr_pos": 0,
                 "raw_pos_atr_neg": 0, "pct_neg_atr_pos": 0, "pct_pos_atr_neg": 0,
                 "all_same_sign": 0, "any_zero": 0, "missing": 0}
        for b in aligned:
            r = b.get(raw_key)
            p = b.get(pct_key)
            a = b.get(atr_key)
            if r is None or p is None or a is None:
                signs["missing"] += 1
                continue
            sr = 1 if r > 0 else (-1 if r < 0 else 0)
            sp = 1 if p > 0 else (-1 if p < 0 else 0)
            sa = 1 if a > 0 else (-1 if a < 0 else 0)
            if sr == 0 or sp == 0 or sa == 0:
                signs["any_zero"] += 1
                continue
            if sr == sp == sa:
                signs["all_same_sign"] += 1
            else:
                if sr < 0 and sp > 0: signs["raw_neg_pct_pos"] += 1
                elif sr > 0 and sp < 0: signs["raw_pos_pct_neg"] += 1
                if sr < 0 and sa > 0: signs["raw_neg_atr_pos"] += 1
                elif sr > 0 and sa < 0: signs["raw_pos_atr_neg"] += 1
                if sp < 0 and sa > 0: signs["pct_neg_atr_pos"] += 1
                elif sp > 0 and sa < 0: signs["pct_pos_atr_neg"] += 1
        n_eval = len(aligned) - signs["missing"] - signs["any_zero"]
        if n_eval == 0:
            continue
        same_pct = signs["all_same_sign"] / n_eval * 100
        diverg = n_eval - signs["all_same_sign"]
        verdict = "OK" if diverg == 0 else f"DIVERG {diverg}/{n_eval} ({100 - same_pct:.0f}%)"
        print(f"  {lvl_name:12s} : same={signs['all_same_sign']:3d} diverg={diverg:3d} "
              f"raw_vs_pct={signs['raw_neg_pct_pos']+signs['raw_pos_pct_neg']:3d} "
              f"raw_vs_atr={signs['raw_neg_atr_pos']+signs['raw_pos_atr_neg']:3d} "
              f"pct_vs_atr={signs['pct_neg_atr_pos']+signs['pct_pos_atr_neg']:3d} -> {verdict}")

    # Bug E : % bars où dist_*_atr clamped à ±5
    print(f"\n--- BUG E : Frequence clamp ±5 (sur {len(aligned)} bars) ---")
    atr_features = [
        "dist_ib_high_atr", "dist_ib_low_atr",
        "dist_sess_high_atr", "dist_sess_low_atr",
        "dist_cur_vpoc_atr", "dist_cur_vah_atr", "dist_cur_val_atr",
        "dist_prev_vpoc_atr", "dist_prev_vah_atr", "dist_prev_val_atr",
        "dist_pdh_atr", "dist_pdl_atr",
        "dist_mq_call_atr", "dist_mq_put_atr", "dist_mq_hvl_atr",
        "dist_vwap_d_atr", "dist_vwap_w_atr", "dist_vwap_m_atr",
    ]
    for feat in atr_features:
        clamped_plus = 0
        clamped_minus = 0
        active = 0
        nulls = 0
        for b in aligned:
            v = b.get(feat)
            if v is None:
                nulls += 1
                continue
            if v >= 4.99:
                clamped_plus += 1
            elif v <= -4.99:
                clamped_minus += 1
            else:
                active += 1
        total = clamped_plus + clamped_minus + active
        if total == 0:
            continue
        clamp_pct = (clamped_plus + clamped_minus) / total * 100
        flag = "🔴 SATURÉ" if clamp_pct > 50 else "🟡 partiel" if clamp_pct > 20 else "✓ OK"
        print(f"  {feat:25s} : +5={clamped_plus:3d} -5={clamped_minus:3d} "
              f"active={active:3d} ({clamp_pct:5.1f}% clamped) null={nulls:3d} {flag}")


# Run sur 3 symboles
for sym, sym_fs in [("ES", "ES"), ("NQ", "NQ"), ("MGC", "GC")]:
    p = ROOT / "DATA" / "live_enriched" / sym_fs / f"20260515_{sym_fs}.jsonl"
    analyze_file(p, sym)
