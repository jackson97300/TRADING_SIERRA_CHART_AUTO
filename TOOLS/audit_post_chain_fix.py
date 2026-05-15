"""Re-audit NaN apres fix chain phase_b_plus_plus (footprint_builder_streaming
deploye 06:32). Compare BEFORE (bars 1-6 corrompues) vs AFTER (bars 7+) puis
versus V4 batch ground truth.
"""
import json
import pandas as pd
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_jsonl(path):
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line.replace("NaN", "null")))
    return pd.DataFrame(rows)


for sym, fs in [("NQ.c.0", "NQ_c_0"), ("ES.c.0", "ES_c_0"), ("MGC.v.0", "MGC_v_0")]:
    p = ROOT / "DATA" / "live_enriched" / fs / "20260515.jsonl"
    df = load_jsonl(p)
    print(f"\n=== {sym} : {len(df)} bars / {len(df.columns)} cols ===")

    # Separe bars avant/apres fix chain (cutoff ts_event_ns = 1778841120000000000 = 10:32:00 UTC)
    cutoff_ns = 1778841120000000000  # 06:32 ET = 10:32 UTC
    df["is_after_chain_fix"] = df["ts_event_ns"] >= cutoff_ns
    n_before = (~df["is_after_chain_fix"]).sum()
    n_after = df["is_after_chain_fix"].sum()
    print(f"  BEFORE chain fix : {n_before} bars / AFTER : {n_after} bars")

    if n_after > 0:
        df_post = df[df["is_after_chain_fix"]]
        # NaN ratio POST fix
        nan_ratios = {}
        for c in df_post.columns:
            if df_post[c].dtype.kind in "fc":
                nan_ratios[c] = df_post[c].isna().mean()
        fully_nan_post = sorted([c for c, r in nan_ratios.items() if r >= 0.99])
        print(f"  POST-fix : {len(fully_nan_post)} features 100% NaN sur {n_after} bars")

        # Categorise
        suspect_post = []
        for c in fully_nan_post:
            if c.startswith(("ib_", "cash_", "us_", "after_", "ovn_", "open_830", "open_930")):
                continue  # pre-RTH legit
            if c in ("im_ltr_slope_diff", "open_cash", "price_1030"):
                continue  # R1 / pre-RTH
            if c.endswith("_0dte") or "0dte" in c:
                continue  # 0DTE legit
            if c.startswith("dist_") and ("0dte" in c or "swing" in c or "trapped" in c or "delta_div" in c or "big_" in c or "cluster" in c or "ovn" in c or "ib_" in c or "cash" in c or "us_" in c or "after" in c or "open_830" in c or "open_930" in c):
                continue  # event-based
            if c.startswith("im_") and c in ("im_delta_day_divergence", "im_volume_lead"):
                continue
            suspect_post.append(c)

        print(f"  SUSPECTS POST-fix ({len(suspect_post)}) :")
        for c in suspect_post[:30]:
            print(f"    - {c}")
        if len(suspect_post) > 30:
            print(f"    ... ({len(suspect_post)-30} more)")
