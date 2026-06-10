"""
Audit fidelite replay : pour chaque feature DMP (267 cols), determiner si
elle est REPRODUITE FIDELEMENT par un Full Recalc/Replay vs live original.

Methode : sur les bars COMMUNES (memes timestamps PRE_FIX live vs POST replay),
compare les valeurs feature par feature.

Verdict :
  IDENTICAL  : 100% memes valeurs (replay reproduit parfaitement)
  FIDELE     : >=95% memes valeurs
  PARTIELLE  : 70-95% (tolerable)
  DIVERGE    : 30-70% (replay altere)
  NONFIDELE  : <30% (replay non-fiable)
  DEAD_LIVE  : PRE=0% AND POST=0% (mort des deux cotes, pas analysable)
  DEAD_REPLAY: PRE>0% AND POST=0% (live capture, replay rate)
  GAINED     : PRE=0% AND POST>0% (replay capture qch en plus = suspect ?)

Output : tableau global ES+NQ avec categorisation.
"""
import json
from collections import defaultdict, Counter

ROOT = "d:/TRADING_SIERRA_CHART_AUTO"


def load_jsonl(path):
    bars = {}
    with open(path, encoding="utf-8") as f:
        for l in f:
            try:
                b = json.loads(l)
                ts = b.get("ts")
                if ts is not None:
                    bars[ts] = b
            except Exception:
                continue
    return bars


def values_match(v1, v2, tol=1e-6):
    if v1 is None and v2 is None:
        return True
    if v1 is None or v2 is None:
        return False
    if isinstance(v1, (int, float)) and isinstance(v2, (int, float)):
        try:
            return abs(float(v1) - float(v2)) < tol
        except Exception:
            return False
    return v1 == v2


def is_meaningful(v):
    return v not in (None, 0, 0.0, "")


def categorize_feature(pre_vals, post_vals, n_common):
    if not pre_vals or not post_vals:
        return "MISSING", 0
    matches = sum(1 for v1, v2 in zip(pre_vals, post_vals) if values_match(v1, v2))
    pct_match = matches / n_common * 100 if n_common else 0

    pre_meaningful = sum(1 for v in pre_vals if is_meaningful(v))
    post_meaningful = sum(1 for v in post_vals if is_meaningful(v))

    if pre_meaningful == 0 and post_meaningful == 0:
        return "DEAD_BOTH", 100  # mort des 2 cotes
    if pre_meaningful > 0 and post_meaningful == 0:
        return "DEAD_REPLAY", pct_match  # live a, replay non
    if pre_meaningful == 0 and post_meaningful > 0:
        return "GAINED_REPLAY", pct_match  # replay capture qch en plus
    if pct_match >= 99.99:
        return "IDENTICAL", pct_match
    if pct_match >= 95:
        return "FIDELE", pct_match
    if pct_match >= 70:
        return "PARTIELLE", pct_match
    if pct_match >= 30:
        return "DIVERGE", pct_match
    return "NONFIDELE", pct_match


def audit(sym):
    pre_path = f"{ROOT}/DATA/{sym}/20260424_{sym}_PRE_FIX.jsonl"
    post_path = f"{ROOT}/DATA/{sym}/20260424_{sym}.jsonl"
    pre = load_jsonl(pre_path)
    post = load_jsonl(post_path)
    common_ts = sorted(set(pre.keys()) & set(post.keys()))
    n = len(common_ts)
    print(f"=== {sym} : {n} bars communes (PRE={len(pre)} POST={len(post)}) ===")

    # All keys union
    all_keys = set()
    for ts in common_ts[:5]:  # echantillon pour rapide
        all_keys.update(pre[ts].keys())
        all_keys.update(post[ts].keys())

    results = {}
    for k in sorted(all_keys):
        pre_vals = [pre[ts].get(k) for ts in common_ts]
        post_vals = [post[ts].get(k) for ts in common_ts]
        cat, pct = categorize_feature(pre_vals, post_vals, n)
        results[k] = (cat, pct)
    return results


def main():
    print("=" * 100)
    print("AUDIT FIDELITE REPLAY — 24/04 PRE_FIX live vs POST replay/Full Recalc")
    print("=" * 100)

    es = audit("ES")
    print()
    nq = audit("NQ")
    print()

    # Combined : pour chaque feature, prendre verdict ES + verdict NQ
    all_features = sorted(set(es.keys()) | set(nq.keys()))

    print("=" * 100)
    print("CATEGORISATION COMBINEE")
    print("=" * 100)

    cat_buckets = defaultdict(list)
    for k in all_features:
        cat_es, pct_es = es.get(k, ("MISSING", 0))
        cat_nq, pct_nq = nq.get(k, ("MISSING", 0))
        # Verdict combined : on prend le pire des 2 (le plus conservateur)
        priority = ["DEAD_BOTH", "DEAD_REPLAY", "GAINED_REPLAY", "NONFIDELE",
                    "DIVERGE", "PARTIELLE", "FIDELE", "IDENTICAL", "MISSING"]
        pri_es = priority.index(cat_es) if cat_es in priority else 99
        pri_nq = priority.index(cat_nq) if cat_nq in priority else 99
        worst = cat_es if pri_es < pri_nq else cat_nq
        cat_buckets[worst].append((k, cat_es, pct_es, cat_nq, pct_nq))

    # Print summary
    print()
    print(f"{'Categorie':<18}{'Count':<8}{'Description'}")
    print("-" * 100)
    summaries = {
        "IDENTICAL": "Valeurs 100% identiques replay vs live (= reproductible)",
        "FIDELE": ">=95% identiques (= replay fidele, OK pour reconstitution)",
        "PARTIELLE": "70-95% identiques (= tolerable pour ML)",
        "DIVERGE": "30-70% identiques (= attention)",
        "NONFIDELE": "<30% identiques (= NE PAS utiliser via replay)",
        "DEAD_BOTH": "Mort live + replay (constante 0/null)",
        "DEAD_REPLAY": "Live capture, replay rate (= live-only feature)",
        "GAINED_REPLAY": "Live=0, replay capture (suspect)",
        "MISSING": "Feature absente",
    }
    for cat in ["IDENTICAL", "FIDELE", "PARTIELLE", "DIVERGE", "NONFIDELE",
                "DEAD_BOTH", "DEAD_REPLAY", "GAINED_REPLAY", "MISSING"]:
        n = len(cat_buckets[cat])
        if n:
            print(f"{cat:<18}{n:<8}{summaries.get(cat, '')}")

    # Detail DEAD_REPLAY (= features live-only critiques)
    print()
    print("=" * 100)
    print("DEAD_REPLAY (features live-only — replay rate ce que live capture)")
    print("=" * 100)
    for k, cat_es, pct_es, cat_nq, pct_nq in cat_buckets["DEAD_REPLAY"]:
        print(f"  {k:<35} ES:{cat_es}({pct_es:.0f}%)  NQ:{cat_nq}({pct_nq:.0f}%)")

    # Detail NONFIDELE
    print()
    print("=" * 100)
    print("NONFIDELE (replay altere — ne pas utiliser pour 6 mois reconstitution)")
    print("=" * 100)
    for k, cat_es, pct_es, cat_nq, pct_nq in cat_buckets["NONFIDELE"][:30]:
        print(f"  {k:<35} ES:{cat_es}({pct_es:.0f}%)  NQ:{cat_nq}({pct_nq:.0f}%)")
    if len(cat_buckets["NONFIDELE"]) > 30:
        print(f"  ... +{len(cat_buckets['NONFIDELE']) - 30} autres")

    # Detail DIVERGE
    print()
    print("=" * 100)
    print("DIVERGE (replay altere mais partiel)")
    print("=" * 100)
    for k, cat_es, pct_es, cat_nq, pct_nq in cat_buckets["DIVERGE"][:20]:
        print(f"  {k:<35} ES:{cat_es}({pct_es:.0f}%)  NQ:{cat_nq}({pct_nq:.0f}%)")

    # Detail GAINED
    print()
    print("=" * 100)
    print("GAINED_REPLAY (replay capture en plus — verifier coherence)")
    print("=" * 100)
    for k, cat_es, pct_es, cat_nq, pct_nq in cat_buckets["GAINED_REPLAY"]:
        print(f"  {k:<35} ES:{cat_es}({pct_es:.0f}%)  NQ:{cat_nq}({pct_nq:.0f}%)")

    # Verdict final
    print()
    print("=" * 100)
    print("VERDICT STRATEGIQUE")
    print("=" * 100)
    total = sum(len(v) for v in cat_buckets.values())
    safe = (len(cat_buckets["IDENTICAL"]) + len(cat_buckets["FIDELE"])
            + len(cat_buckets["PARTIELLE"]))
    unsafe = (len(cat_buckets["DIVERGE"]) + len(cat_buckets["NONFIDELE"])
              + len(cat_buckets["DEAD_REPLAY"]))
    print(f"  Total features audit : {total}")
    print(f"  REPLAY-SAFE (>=70% match)   : {safe} ({safe*100//total}%)")
    print(f"  REPLAY-UNSAFE (<70% ou dead): {unsafe} ({unsafe*100//total}%)")
    print(f"  Strategie 6 mois data via replay :")
    print(f"    -> {safe} features utilisables")
    print(f"    -> {unsafe} features a NE PAS reconstituer (= live only)")


if __name__ == "__main__":
    main()
