"""
Verifie le fix bn_absorb_ask/bid apres replay 24/04.

Compare :
  - 20260424_ES_PRE_FIX.jsonl (avant fix, lit SG1 Color Bar = 100% zero)
  - 20260424_ES.jsonl         (apres replay avec nouveau DMP, lit Extension Lines)

Idem NQ.

Output : verdict GO / NOGO du fix + stats par feature.
"""
import json
import sys
from collections import Counter

ROOT = "d:/TRADING_SIERRA_CHART_AUTO"


def load_bars(path):
    bars = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                try:
                    bars.append(json.loads(line))
                except Exception:
                    continue
    except OSError as e:
        print(f"ERR load {path}: {e}")
    return bars


def stats_feature(bars, feat):
    vals = [b.get(feat) for b in bars]
    nonnull = [v for v in vals if v is not None]
    if not nonnull:
        return {"n": 0, "nonzero_pct": 0.0, "zero": 0, "nonzero": 0, "max": 0, "uniq": 0}
    nonzero = sum(1 for v in nonnull if v not in (0, 0.0, None))
    return {
        "n": len(nonnull),
        "nonzero_pct": nonzero / len(nonnull) * 100,
        "zero": len(nonnull) - nonzero,
        "nonzero": nonzero,
        "max": max(nonnull) if nonnull else 0,
        "uniq": len(set(nonnull)),
    }


def main():
    print("=" * 80)
    print("VERIFICATION FIX bn_absorb_* (replay 24/04)")
    print("=" * 80)

    pairs = [
        ("ES", f"{ROOT}/DATA/ES/20260424_ES_PRE_FIX.jsonl",
                f"{ROOT}/DATA/ES/20260424_ES.jsonl"),
        ("NQ", f"{ROOT}/DATA/NQ/20260424_NQ_PRE_FIX.jsonl",
                f"{ROOT}/DATA/NQ/20260424_NQ.jsonl"),
    ]

    features = ["bn_absorb_ask", "bn_absorb_bid"]
    verdict_global = "GO"

    for sym, old_path, new_path in pairs:
        print(f"\n{'='*60}")
        print(f"  {sym}")
        print(f"{'='*60}")

        old_bars = load_bars(old_path)
        new_bars = load_bars(new_path)
        print(f"  PRE_FIX bars : {len(old_bars)}")
        print(f"  POST_FIX bars: {len(new_bars)}")

        if not old_bars or not new_bars:
            print(f"  [SKIP] {sym} - pas de bars")
            continue

        for feat in features:
            old_s = stats_feature(old_bars, feat)
            new_s = stats_feature(new_bars, feat)

            print(f"\n  --- {feat} ---")
            print(f"    PRE_FIX  : {old_s['nonzero_pct']:.2f}% non-zero "
                  f"({old_s['nonzero']}/{old_s['n']}) max={old_s['max']}")
            print(f"    POST_FIX : {new_s['nonzero_pct']:.2f}% non-zero "
                  f"({new_s['nonzero']}/{new_s['n']}) max={new_s['max']}")

            delta = new_s["nonzero_pct"] - old_s["nonzero_pct"]

            # Verdict feature
            if old_s["nonzero_pct"] == 0 and new_s["nonzero_pct"] > 0:
                v = "GO - feature reactivee"
            elif old_s["nonzero_pct"] == 0 and new_s["nonzero_pct"] == 0:
                v = "NOGO - toujours 100% zero (fix invalide ou replay incomplet)"
                verdict_global = "NOGO"
            elif new_s["nonzero_pct"] > old_s["nonzero_pct"] * 1.5:
                v = "GO - fort improvement"
            elif new_s["nonzero_pct"] >= 80:
                v = "WARNING - saturation possible (>80% non-zero, suspect)"
                if verdict_global == "GO":
                    verdict_global = "WARNING"
            else:
                v = f"DELTA {delta:+.2f}%"

            print(f"    VERDICT  : {v}")

    print(f"\n{'='*80}")
    print(f"  VERDICT GLOBAL : {verdict_global}")
    print(f"{'='*80}")

    if verdict_global == "GO":
        print("  Fix bn_absorb_* valide. Brèche colmatée.")
        print("  Prochaine etape : appliquer meme procedure aux autres features mortes.")
        return 0
    elif verdict_global == "WARNING":
        print("  Fix actif mais saturation possible - verifier visuellement la coherence.")
        return 1
    else:
        print("  Fix INVALIDE - investiguer pourquoi feature reste 100% zero.")
        print("  Possibles : replay incomplet, Extension Lines pas activees,")
        print("  fix code mauvais, ou ABSORB events ne se reproduisent pas en replay.")
        return 2


if __name__ == "__main__":
    sys.exit(main())
