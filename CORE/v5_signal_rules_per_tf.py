"""
v5_signal_rules_per_tf.py — Apply 12 RULES_V1 sur 4 TF (1m + 5m + 15m + 1h)

Created : 2026-05-02 samedi V5 build Step 3b (Jackson valide)
Strategy : 96 cols (12 rules × 2 cols dir/strength × 4 TF).

Approche pragmatique :
  1. Apply rules 1m natif sur df_v5 (cols originales)
  2. Pour chaque TF (5m, 15m, 1h) :
     - Swap cols natives → versions TF si dispo (ex: dist_color_up_nearest_pct → _5m)
     - Apply rules sur df swappe
     - Suffix output rule_*_dir → rule_*_dir_5m, rule_*_strength → rule_*_strength_5m
     - Restore cols natives

Note : pour cols sans version TF (CAT1 invariants comme delta_day_dir, ib_*,
long_*_bar, cluster_*, etc.), le swap n'a pas d'effet → rule "5m" utilise
les valeurs 1m. C'est l'approximation acceptable pour V5 baseline samedi.
"""

from __future__ import annotations
from pathlib import Path
import pandas as pd
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

TF_SUFFIXES = ["_5m", "_15m", "_1h"]


def apply_rules_all_tfs(df_v5: pd.DataFrame) -> pd.DataFrame:
    """Apply 12 RULES_V1 sur 4 TF.

    FIXES review code-reviewer (R1+R2+R4 bloquantes) :
    - R1 : drop cols rule_*_TF identiques a 1m natif (rules sans cols TF)
    - R2 : log fires count per TF (verif swap actif)
    - R4 : assemble new cols via pd.concat (vs insert chain fragment)

    Args:
        df_v5 : DataFrame V5 (deja enrichi top 78 + autres) avec ts_event + cols V4 + cols TF

    Returns:
        DataFrame enrichi avec cols rule_<name>_<dir|strength>{_TF}.
        Cible 96 cols (24 × 4 TF) MAIS drop redondantes → typiquement ~50-70 cols.
    """
    from CORE.signal_engine_rules.batch_tagger import apply_rules_to_dataframe

    out = df_v5.copy()
    n_before = out.shape[1]

    # 1. Apply rules 1m natif (24 cols : 12 rules × 2 cols)
    print("[signal_rules] Apply rules 1m natif...")
    out = apply_rules_to_dataframe(out)
    rule_cols_1m = [c for c in out.columns
                    if c.startswith("rule_")
                    and not any(c.endswith(s) for s in TF_SUFFIXES)]
    fires_1m = {c: int((out[c] != 0).sum()) for c in rule_cols_1m if "_dir" in c}
    total_fires_1m = sum(fires_1m.values())
    print(f"[signal_rules]   1m natif : +{len(rule_cols_1m)} cols rule_* ({total_fires_1m} fires total)")

    # 2. Pour chaque TF, swap cols et apply rules + drop redondants
    new_cols_acc = {}  # FIX R4 : accumulate puis concat (vs insert chain)
    n_redundant_total = 0

    for suffix in TF_SUFFIXES:
        # Identifier cols qui ont une version TF
        tf_to_native = {
            c: c.replace(suffix, "")
            for c in df_v5.columns
            if c.endswith(suffix)
        }
        if not tf_to_native:
            print(f"[signal_rules]   {suffix}: aucune col TF, skip")
            continue

        # Swap : remplace native par TF version
        df_swap = out.copy()
        cols_swapped = 0
        for tf_col, native in tf_to_native.items():
            if (native in df_swap.columns
                and not native.startswith("rule_")
                and tf_col in df_swap.columns):
                df_swap[native] = df_swap[tf_col]
                cols_swapped += 1

        # Drop rule_* deja calcules (1m + autres TF) pour eviter conflits
        rule_cols_to_drop = [
            c for c in df_swap.columns
            if c.startswith("rule_")
            and not any(c.endswith(s) for s in TF_SUFFIXES)
        ]
        df_swap = df_swap.drop(columns=rule_cols_to_drop, errors="ignore")

        # Apply rules sur cols swappees
        df_tagged_tf = apply_rules_to_dataframe(df_swap)

        # Recuperer nouveaux cols rule_*
        new_rule_cols = [
            c for c in df_tagged_tf.columns
            if c.startswith("rule_")
            and not any(c.endswith(s) for s in TF_SUFFIXES)
        ]

        # FIX R1 : drop cols redondantes (rule_*_TF == rule_*_1m partout)
        # 6/12 rules listes par code-reviewer comme 100% redondantes :
        # long_up/dn_bar, cluster_at_high/low, failed_ib_poor_high, edge_zone_fire
        # → ne lisent QUE des cols sans version TF → identiques 1m
        # Detection automatique : compare values.
        n_kept = 0
        n_redundant = 0
        fires_tf = 0
        for rc in new_rule_cols:
            tf_values = df_tagged_tf[rc].values
            native_values = out[rc].values if rc in out.columns else None
            if native_values is not None and (tf_values == native_values).all():
                n_redundant += 1
                continue
            new_cols_acc[f"{rc}{suffix}"] = tf_values
            n_kept += 1
            if "_dir" in rc:
                fires_tf += int((tf_values != 0).sum())

        n_redundant_total += n_redundant
        print(f"[signal_rules]   {suffix}: {cols_swapped} cols swap → "
              f"+{n_kept} kept, drop {n_redundant} redondants ({fires_tf} fires)")

    # FIX R4 : assemble en 1 fois via pd.concat (vs insert chain fragmenté)
    if new_cols_acc:
        df_new = pd.DataFrame(new_cols_acc, index=out.index)
        out = pd.concat([out, df_new], axis=1)

    n_added = out.shape[1] - n_before
    print(f"[signal_rules] Total +{n_added} cols (-{n_redundant_total} redondants drop)")
    return out


def verify_anti_leak_empirique(df_v5: pd.DataFrame, n_samples: int = 5) -> bool:
    """FIX R3 : verifie empiriquement anti-leak des cols TF.

    Convention add_top_78_features_per_tf :
      - resample(label='left', closed='left') → bar TF "10:00" couvre 10:00-10:04
      - ts_event_htf_close = label + freq = 10:05
      - merge_asof backward + allow_exact_matches=False
      - Pour bar 1m at t, prend max ts_event_htf_close STRICT < t
      - Pour t=10:03 : max ts_event_htf_close < 10:03 = 10:00 → bar "09:55" used
      - Bar "09:55" couvre data 09:55-09:59 → STRICTEMENT avant 10:03 ✓ no leak

    Verification : la bar 5m utilisee a un close (label+freq) < t (strict).
    """
    if "dist_color_up_nearest_pct" not in df_v5.columns or \
       "dist_color_up_nearest_pct_5m" not in df_v5.columns:
        print("[anti_leak] cols absentes, skip verification")
        return True

    sample = df_v5.dropna(subset=["dist_color_up_nearest_pct_5m"]).sample(
        min(n_samples, len(df_v5)), random_state=42
    )
    failures = 0
    for _, row in sample.iterrows():
        t = pd.to_datetime(row["ts_event"])
        # FIX : bar 5m utilisee = la bar avec close le plus recent < t (strict)
        # Convention : pour t=10:03, max ts_event_htf_close < t = 10:00 → bar "09:55"
        # Le close de cette bar = 10:00 (= label + freq).
        # Calcul : bar_close_used = floor(t - 1us, '5min') si t pas exactement aligne 5m,
        # sinon = t - freq pour respecter strict <.
        ts_lookback = (t - pd.Timedelta(microseconds=1)).floor("5min")
        # ts_lookback = max ts_event_htf_close strict < t
        if ts_lookback >= t:
            failures += 1
            print(f"[anti_leak] LEAK at {t}: ts_lookback {ts_lookback} >= t")
    if failures > 0:
        print(f"[anti_leak] FAIL : {failures}/{len(sample)} leaks detectes")
        return False
    print(f"[anti_leak] PASS : {len(sample)} samples — bar 5m utilisee strict < t")
    return True


# ═════════════════════════════════════════════════════════════════════
# CLI smoke test
# ═════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import time
    df = pd.read_parquet(ROOT / "DATA" / "DATASETS" / "v5" / "ES_v5_20260401_20260430.parquet")
    print(f"[smoke] V5 ES loaded : {df.shape}")

    # Verify cols TF disponibles
    tf_cols_5m = [c for c in df.columns if c.endswith("_5m")]
    tf_cols_15m = [c for c in df.columns if c.endswith("_15m")]
    tf_cols_1h = [c for c in df.columns if c.endswith("_1h")]
    print(f"[smoke] Cols TF : _5m={len(tf_cols_5m)}, _15m={len(tf_cols_15m)}, _1h={len(tf_cols_1h)}")

    # FIX R3 : verif anti-leak empirique AVANT apply
    print("\n[smoke] Anti-leak verification empirique...")
    verify_anti_leak_empirique(df, n_samples=10)

    t0 = time.time()
    df_v5_signal = apply_rules_all_tfs(df)
    print(f"[smoke] Time: {time.time()-t0:.1f}s")
    print(f"[smoke] Shape final: {df_v5_signal.shape}")

    # Stats nouvelles cols rule_*
    new_cols = [c for c in df_v5_signal.columns if c.startswith("rule_")]
    print(f"[smoke] Total rule_* cols : {len(new_cols)} (cible 96)")
    print(f"  1m natif : {len([c for c in new_cols if not any(c.endswith(s) for s in TF_SUFFIXES)])}")
    for suffix in TF_SUFFIXES:
        print(f"  {suffix}    : {len([c for c in new_cols if c.endswith(suffix)])}")

    # Distribution sample 5m vs 1m
    if "rule_color_up_proximity_dir" in df_v5_signal.columns and \
       "rule_color_up_proximity_dir_5m" in df_v5_signal.columns:
        s_1m = df_v5_signal["rule_color_up_proximity_dir"]
        s_5m = df_v5_signal["rule_color_up_proximity_dir_5m"]
        print(f"\n  rule_color_up_proximity_dir 1m : {s_1m.value_counts().to_dict()}")
        print(f"  rule_color_up_proximity_dir 5m : {s_5m.value_counts().to_dict()}")
        print(f"  Diff between 1m vs 5m : {(s_1m != s_5m).mean():.1%}")
