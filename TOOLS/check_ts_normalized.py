"""check_ts_normalized.py - Verification automatisee Phase 1.5 ts normalisation.

Anti-VALIDATION_MISS (cf feedback_validation_miss_pre_deploy.md, 9+ occurrences).

A executer J+1 et J+7 post-deploy fix jitter ts (CORE/sierra_ts.py).

Critere succes :
  100% des bars sample doivent avoir :
    - ts % 60000 == 0 (multiple de minute)
    - ts_raw_ms present (preservation brut)
    - ts_event ISO coherent avec ts ms
    - ts_event_ns = ts * 1_000_000 coherent

Si KO -> rollback fix + investiguer pourquoi normalize_payload_ts pas applique.

Usage :
    python tools/check_ts_normalized.py \\
        --input DATA/_AUDIT/20260613_NQ_live.jsonl \\
        --sample 1000
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


def check_bar(bar: dict) -> list[str]:
    """Return list of errors for one bar. Empty list = OK."""
    errors = []
    ts = bar.get("ts")
    if ts is None:
        return ["ts absent"]
    if not isinstance(ts, (int, float)):
        return [f"ts non-numerique: {type(ts).__name__}"]
    if ts % 60_000 != 0:
        errors.append(f"ts % 60000 = {ts % 60_000} (jitter non corrige)")
    if "ts_raw_ms" not in bar:
        errors.append("ts_raw_ms absent (preservation brut casse)")
    # Coherence ts_event
    ts_event = bar.get("ts_event")
    if ts_event is not None:
        expected_iso = datetime.fromtimestamp(ts / 1000.0, tz=timezone.utc).isoformat()
        if ts_event != expected_iso:
            errors.append(f"ts_event incoherent: {ts_event!r} vs attendu {expected_iso!r}")
    # Coherence ts_event_ns
    ts_event_ns = bar.get("ts_event_ns")
    if ts_event_ns is not None and ts_event_ns != int(ts) * 1_000_000:
        errors.append(f"ts_event_ns incoherent: {ts_event_ns} vs attendu {int(ts) * 1_000_000}")
    return errors


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--sample", type=int, default=1000,
                         help="Nombre de bars a verifier depuis le DEBUT (defaut 1000)")
    parser.add_argument("--tail", action="store_true",
                         help="Verifier les SAMPLE dernieres bars (au lieu du debut)")
    args = parser.parse_args()

    # Load bars
    bars = []
    with open(args.input, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                bars.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    if not bars:
        print("ERROR: 0 bars chargees")
        return 1

    if args.tail:
        bars_to_check = bars[-args.sample:]
    else:
        bars_to_check = bars[:args.sample]

    print(f"=> Verifie {len(bars_to_check)} bars (sur {len(bars)} totales)")

    n_ok = 0
    n_ko = 0
    errors_summary = {}
    sample_errors = []
    for i, bar in enumerate(bars_to_check):
        errs = check_bar(bar)
        if not errs:
            n_ok += 1
        else:
            n_ko += 1
            for e in errs:
                key = e.split(":")[0]
                errors_summary[key] = errors_summary.get(key, 0) + 1
            if len(sample_errors) < 5:
                ts = bar.get("ts", "?")
                sample_errors.append(f"  bar[{i}] ts={ts} : {errs}")

    print(f"\n=== RESULTATS ===")
    print(f"OK    : {n_ok}/{len(bars_to_check)} ({100.0 * n_ok / len(bars_to_check):.1f}%)")
    print(f"KO    : {n_ko}/{len(bars_to_check)} ({100.0 * n_ko / len(bars_to_check):.1f}%)")

    if errors_summary:
        print(f"\nErrors breakdown:")
        for k, v in sorted(errors_summary.items(), key=lambda x: -x[1]):
            print(f"  {k:50s} : {v}")
        print(f"\nSample errors (max 5):")
        for s in sample_errors:
            print(s)

    if n_ko > 0:
        print(f"\n[FAIL] {n_ko} bars KO. Rollback ou investigation immediate.")
        return 1
    print(f"\n[OK] 100% bars normalisees correctement.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
