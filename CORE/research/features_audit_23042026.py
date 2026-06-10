"""
Audit features ES + NQ du 23/04/2026 : detection MORTES + SUSPECTES.

Categories :
  MORTE       : 99%+ bars meme valeur (constante) OU 99%+ NULL
  QUASI-MORTE : 90-99% meme valeur
  SUSPECTE    : >70% meme valeur OU outliers extremes (p99/median > 50)
  SAINE       : distribution riche (>=4 valeurs distinctes >5%)

Output : tableau categorise pour chaque feature.
"""
import json
from collections import Counter
from statistics import median, stdev

ROOT = "d:/TRADING_SIERRA_CHART_AUTO"


def load_bars(sym, date_str):
    path = f"{ROOT}/DATA/{sym}/{date_str}_{sym}.jsonl"
    bars = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                try:
                    bars.append(json.loads(line))
                except Exception:
                    continue
    except OSError:
        pass
    return bars


def analyze_feature(values, total_bars):
    """Categorise une feature."""
    not_null = [v for v in values if v is not None]
    null_count = total_bars - len(not_null)
    if null_count >= 0.99 * total_bars:
        return "MORTE", f"{null_count}/{total_bars} NULL ({null_count/total_bars*100:.0f}%)"
    if not not_null:
        return "MORTE", "0 valeur non-null"

    counts = Counter(not_null)
    most_common_v, most_common_n = counts.most_common(1)[0]
    pct_top = most_common_n / total_bars * 100

    if pct_top >= 99:
        return "MORTE", f"{most_common_v} sur {pct_top:.0f}% (constante)"
    if pct_top >= 90:
        return "QUASI-MORTE", f"{most_common_v} sur {pct_top:.0f}%"

    # Outliers
    try:
        nums = [float(v) for v in not_null]
    except (TypeError, ValueError):
        # Categorical (str)
        if pct_top >= 70:
            return "SUSPECTE", f"top val {most_common_v} {pct_top:.0f}%"
        return "SAINE-CAT", f"{len(counts)} valeurs distinctes"

    if pct_top >= 70:
        return "SUSPECTE", f"top val {most_common_v} {pct_top:.0f}%"

    nums_sorted = sorted(nums)
    p50 = nums_sorted[len(nums_sorted) // 2]
    p99 = nums_sorted[int(len(nums_sorted) * 0.99)] if len(nums_sorted) > 100 else nums_sorted[-1]
    p_max = max(nums_sorted)
    if p50 != 0 and abs(p_max / p50) > 100:
        return "OUTLIER", f"max/p50 = {p_max/p50:.0f}x"
    if p50 != 0 and abs(p99 / p50) > 50:
        return "OUTLIER-MIN", f"p99/p50 = {p99/p50:.0f}x"

    sig_count = sum(1 for c in counts.values() if c >= 0.05 * total_bars)
    if sig_count >= 4:
        return "SAINE", f"{sig_count}+ buckets >5%"
    return "POOR", f"{sig_count} buckets >5%"


def main():
    DATE = "20260423"
    print("=" * 100)
    print(f"AUDIT FEATURES ES + NQ — {DATE}")
    print("=" * 100)

    for sym in ("ES", "NQ"):
        bars = load_bars(sym, DATE)
        if not bars:
            print(f"\n[{sym}] no bars")
            continue
        n = len(bars)
        # Collect all keys
        all_keys = set()
        for b in bars:
            all_keys.update(b.keys())
        print(f"\n[{sym}] {n} bars, {len(all_keys)} keys totales")

        # Categorize each
        cats = {"MORTE": [], "QUASI-MORTE": [], "SUSPECTE": [], "OUTLIER": [],
                "OUTLIER-MIN": [], "SAINE": [], "POOR": [], "SAINE-CAT": []}
        for k in sorted(all_keys):
            vals = [b.get(k) for b in bars]
            cat, detail = analyze_feature(vals, n)
            cats[cat].append((k, detail))

        # Print summary
        print(f"  Categorisation :")
        for c in ("MORTE", "QUASI-MORTE", "SUSPECTE", "OUTLIER", "OUTLIER-MIN", "POOR", "SAINE-CAT", "SAINE"):
            print(f"    {c:<14} : {len(cats[c]):>3}")

        # Detail MORTES
        print(f"\n  === MORTES ({len(cats['MORTE'])}) — a investiguer ===")
        for k, d in cats["MORTE"]:
            print(f"    {k:<35} : {d}")

        # Detail QUASI-MORTES
        if cats["QUASI-MORTE"]:
            print(f"\n  === QUASI-MORTES ({len(cats['QUASI-MORTE'])}) — fortement bias ===")
            for k, d in cats["QUASI-MORTE"]:
                print(f"    {k:<35} : {d}")

        # Detail SUSPECTES
        if cats["SUSPECTE"]:
            print(f"\n  === SUSPECTES ({len(cats['SUSPECTE'])}) — distribution skewed ===")
            for k, d in cats["SUSPECTE"][:25]:
                print(f"    {k:<35} : {d}")
            if len(cats["SUSPECTE"]) > 25:
                print(f"    ... +{len(cats['SUSPECTE']) - 25} autres")

        # Detail OUTLIERS
        if cats["OUTLIER"] or cats["OUTLIER-MIN"]:
            print(f"\n  === OUTLIERS ({len(cats['OUTLIER']) + len(cats['OUTLIER-MIN'])}) — extremes ===")
            for k, d in cats["OUTLIER"][:10]:
                print(f"    {k:<35} : {d}")
            for k, d in cats["OUTLIER-MIN"][:10]:
                print(f"    {k:<35} : {d}")


if __name__ == "__main__":
    main()
