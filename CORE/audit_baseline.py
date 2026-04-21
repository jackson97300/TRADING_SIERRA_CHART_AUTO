"""
Build baseline stats 4j (15-19/04) pour detection derive post-fix 3.7.8.
Compare avec snapshot 20/04 post-fix, flag features avec derive > 3 std.
"""

from __future__ import annotations

import json
import statistics
from pathlib import Path

AUDIT_DIR = Path(__file__).parent.parent / "DATA" / "AUDIT_20260420"
DATA_ES = Path(__file__).parent.parent / "DATA" / "ES"
DATA_NQ = Path(__file__).parent.parent / "DATA" / "NQ"

BASELINE_DATES = ["20260417"]
POST_FIX_DATE = "20260420"


def load_lines(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(l) for l in open(path, encoding="utf-8")]


def numeric_features(rows: list[dict]) -> set[str]:
    cols = set()
    for r in rows[:50]:
        for k, v in r.items():
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                cols.add(k)
    return cols


def session_stats(rows: list[dict], sess: int, features: set[str]) -> dict:
    """Stats par feature pour session donnee."""
    sess_rows = [r for r in rows if r.get("session") == sess]
    if not sess_rows:
        return {}
    out = {}
    for feat in features:
        vals = [r.get(feat) for r in sess_rows if isinstance(r.get(feat), (int, float))]
        if not vals:
            continue
        mean = sum(vals) / len(vals)
        std = statistics.stdev(vals) if len(vals) > 1 else 0.0
        out[feat] = {"mean": mean, "std": std, "n": len(vals)}
    return out


def main():
    for sym in ["ES", "NQ"]:
        baseline_rows = []
        data_dir = DATA_ES if sym == "ES" else DATA_NQ
        for d in BASELINE_DATES:
            path = data_dir / f"{d}_{sym}.jsonl"
            baseline_rows.extend(load_lines(path))

        post_path = AUDIT_DIR / f"{sym}_frozen.jsonl"
        post_rows = load_lines(post_path)

        if not baseline_rows or not post_rows:
            print(f"{sym} : baseline ou post vide")
            continue

        features = numeric_features(baseline_rows)
        print(f"\n=== {sym} ===")
        print(f"Baseline: {len(baseline_rows)} barres ({len(BASELINE_DATES)} jours)")
        print(f"Post-fix: {len(post_rows)} barres (20/04)")

        # Compare RTH (session=2)
        bl_stats = session_stats(baseline_rows, 2, features)
        post_stats = session_stats(post_rows, 2, features)

        drifts = []
        for feat in features:
            if feat not in bl_stats or feat not in post_stats:
                continue
            bl_mean = bl_stats[feat]["mean"]
            bl_std = bl_stats[feat]["std"]
            post_mean = post_stats[feat]["mean"]
            if bl_std < 1e-6:
                continue
            z = (post_mean - bl_mean) / bl_std
            if abs(z) > 3.0:
                drifts.append((feat, z, bl_mean, post_mean))

        drifts.sort(key=lambda x: -abs(x[1]))
        print(f"Drifts > 3 std (RTH): {len(drifts)}")
        for feat, z, bm, pm in drifts[:15]:
            print(f"  {feat:30s} z={z:+6.1f}  baseline_mean={bm:10.3f}  post_mean={pm:10.3f}")


if __name__ == "__main__":
    main()
