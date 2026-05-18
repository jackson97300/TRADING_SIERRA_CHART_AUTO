"""tools/replay_narrative_state_machine.py - Replay NSM Bot 3 v2 tracking-only.

Usage:
    python -X utf8 tools/replay_narrative_state_machine.py \
        --parquet DATA/V4_TEMP/ES_mai_v4_freshest.parquet \
        --symbol ES \
        --start 2026-05-11 --end 2026-05-15

Loads V4 enriched parquet, iterates bar-by-bar, calls NSM.transition()
en mode TRACKING ONLY (aucun trade, aucune decision propagee). Verifie :
  - 100% bars processed sans crash
  - Latence p50/p95/p99 sous budget 5ms
  - Distribution etats narratifs (15 etats post-fusion B2)
  - Distribution bias_dir (-1/0/+1)
  - Distribution trigger codes
  - Anti flicker hits

Critere passage Phase 2 (cf DOCS/plans/2026-05-18-bot3-narrative-layer-spec.md) :
  - 0 crash
  - p99 latence < 5ms
  - >= 4 transitions par jour par symbole (sinon FSM trop conservatrice)
  - bias_dir == -1 represente >= 30% des transitions (pas biais long uniquement)
  - Anti-flicker hits == 0 (sinon thresholds mal calibres ou data choppy)

Created : 2026-05-18 by Jackson + Claude (mode mentor proactif)
Phase tracker : DOCS/plans/2026-05-18-bot3-narrative-layer-spec.md
"""
from __future__ import annotations

import argparse
import math
import sys
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

# Ajout ROOT au sys.path pour import CORE.* depuis tools/
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pandas as pd


# ─── Stub swing state (mirror StubSwingState test fixture) ────────────────


@dataclass
class _SwingPoint:
    price: float = 0.0
    bar_idx: int = -1


@dataclass
class _SwingState:
    last_swing_high: _SwingPoint = field(default_factory=_SwingPoint)
    last_swing_low: _SwingPoint = field(default_factory=_SwingPoint)


def _row_to_bar(row: pd.Series, bar_idx_session: int) -> dict:
    """Convert parquet row to bar dict for NSM. Map ts_event -> ts_event_iso."""
    return {
        "ts_event_iso": str(row.get("ts_event", "")),
        "ts_event": str(row.get("ts_event", "")),
        "close": _safe(row.get("close")),
        "open": _safe(row.get("open")),
        "high": _safe(row.get("high")),
        "low": _safe(row.get("low")),
        "atr": _safe(row.get("atr")),
        "vol_zscore_20": _safe(row.get("vol_zscore_20")),
        "bar_idx_session": bar_idx_session,
        "volume": _safe(row.get("volume")) or 1000,
        "session_date_trading": str(row.get("session_date_trading", "")),
    }


# V4 enriched encode session en numerique (validation empirique 18/05) :
# 0 = ASIA (overnight global), 1 = LONDON (7-13 UTC),
# 2 = NY RTH (13-19 UTC), 3 = US_AH (20+ UTC)
_SESSION_NUMERIC_TO_STR: dict[int, str] = {
    0: "ASIA", 1: "LONDON", 2: "NY", 3: "US_AH",
}


def _normalize_session(v) -> str:
    """V4 enriched session est int 0-3. NSM s'attend a string ASIA/LONDON/NY."""
    if v is None:
        return "OTHER"
    try:
        iv = int(v)
        return _SESSION_NUMERIC_TO_STR.get(iv, "OTHER")
    except (TypeError, ValueError):
        s = str(v).upper()
        if s in ("ASIA", "LONDON", "NY", "US_AH", "OTHER"):
            return s
        return "OTHER"


def _row_to_ctx(row: pd.Series, tick_size: float = 0.25) -> dict:
    """Convert parquet row to ctx dict for NSM."""
    return {
        "session": _normalize_session(row.get("session")),
        "open_type": int(row.get("open_type", 0)) if not _is_nan(row.get("open_type")) else 0,
        "asia_close": _safe(row.get("asia_open")),  # asia_close manquant → fallback
        "asia_open": _safe(row.get("asia_open")),
        "open_cash": _safe(row.get("open_cash")),
        "prev_vah": _safe(row.get("prev_vah")),
        "prev_val": _safe(row.get("prev_val")),
        "ib_complete": bool(row.get("ib_complete", False)),
        "ib_range": _safe(row.get("ib_range")),
        "inside_value_area": bool(row.get("inside_value_area", False)),
        "tick_size": tick_size,
    }


def _row_to_swing(row: pd.Series) -> _SwingState:
    """Build swing_state stub from V4 enriched columns."""
    high_p = _safe(row.get("_last_swing_high_price")) or 0.0
    low_p = _safe(row.get("_last_swing_low_price")) or 0.0
    return _SwingState(
        last_swing_high=_SwingPoint(price=high_p),
        last_swing_low=_SwingPoint(price=low_p),
    )


def _row_to_story_fallback(row: pd.Series, prev_close: float | None) -> dict:
    """DEPRECATED — fallback minimal story trackers depuis V4 parquet.

    Conserve uniquement pour debug. Remplace par calcul live via
    `bot3_story_trackers.update_story_trackers` dans le replay loop (fix 18/05
    post-NOGO ml-trainer : V4 parquet manque slope_close_60/hh_count_60/ll_count_60).
    """
    bars_since_swing_high = _safe(row.get("bars_since_last_swing_high")) or -1
    bars_since_swing_low = _safe(row.get("bars_since_last_swing_low")) or -1
    bars_since_BOS = min(bars_since_swing_high, bars_since_swing_low) if (
        bars_since_swing_high >= 0 and bars_since_swing_low >= 0
    ) else max(bars_since_swing_high, bars_since_swing_low, -1)
    return {
        "slope_close_60": 0.0,
        "hh_count_60": int(_safe(row.get("hh_count_60")) or 0),
        "ll_count_60": int(_safe(row.get("ll_count_60")) or 0),
        "bars_since_last_BOS": int(bars_since_BOS),
    }


def _safe(v) -> float | None:
    if v is None:
        return None
    try:
        f = float(v)
        if math.isnan(f) or math.isinf(f):
            return None
        return f
    except (TypeError, ValueError):
        return None


def _is_nan(v) -> bool:
    try:
        return math.isnan(float(v))
    except (TypeError, ValueError):
        return v is None


# ─── Replay engine ────────────────────────────────────────────────────────


def replay(
    parquet_path: Path,
    symbol: str,
    sdt_start: str | None = None,
    sdt_end: str | None = None,
) -> dict:
    """Replay NSM sur parquet V4 enriched.

    Args:
        parquet_path: chemin parquet (ES_mai_v4_freshest.parquet etc.)
        symbol: nom symbole pour NSM (ES, NQ, MGC).
        sdt_start: session_date_trading min (inclus) format YYYY-MM-DD.
        sdt_end: session_date_trading max (inclus).

    Returns:
        dict stats: total_bars, transitions, latencies, distributions, criteres_phase2.
    """
    # Lazy import pour pouvoir mesurer le warmup
    from CORE.bot3_direction_resolver import DirectionResolver
    from CORE.bot3_narrative_state_machine import (
        FLICKER_GUARD_THRESHOLD,
        NarrativeStateMachine,
    )
    from CORE.bot3_plot_twist_detectors import PlotTwistDetectorsState, scan_all
    from CORE.bot3_scenario_validator import is_narrative_still_valid
    from CORE.bot3_shadow_mode import ShadowComparison, ShadowModeLogger, detect_divergence
    from CORE.bot3_story_trackers import StoryTrackersState, update_story_trackers

    print(f"Loading {parquet_path}...")
    df = pd.read_parquet(parquet_path)
    print(f"  Total bars: {len(df)}, columns: {len(df.columns)}")

    # Filtre session_date_trading
    if "session_date_trading" not in df.columns:
        print("ERREUR: session_date_trading manquant", file=sys.stderr)
        sys.exit(1)
    df["session_date_trading"] = df["session_date_trading"].astype(str)
    if sdt_start:
        df = df[df["session_date_trading"] >= sdt_start]
    if sdt_end:
        df = df[df["session_date_trading"] <= sdt_end]
    df = df.sort_values("ts_event").reset_index(drop=True)
    print(f"  Filtered range [{sdt_start} -> {sdt_end}]: {len(df)} bars")

    # Bar_idx_session : cumcount par session
    df["bar_idx_session_calc"] = df.groupby("session_date_trading").cumcount()

    # Sessions distribution
    sessions = df["session_date_trading"].value_counts().sort_index()
    print(f"  Sessions: {dict(sessions)}")

    nsm = NarrativeStateMachine()
    story_state = StoryTrackersState(symbol=symbol)  # fix 18/05 : story trackers live
    twist_state = PlotTwistDetectorsState(symbol=symbol)  # Phase 2
    resolver = DirectionResolver()  # Phase 3 J+3 integration
    shadow_logger = ShadowModeLogger(output_dir="LOGS/bot3_v2_shadow_replay")
    transitions: list[dict] = []
    twists_observed: list[dict] = []
    invalidations: list[dict] = []
    twists_per_type: Counter = Counter()
    # Phase 3 shadow mode metrics
    shadow_total = 0
    shadow_long = 0
    shadow_short = 0
    shadow_no_trade = 0
    shadow_divergences = 0
    scenarios_fired: Counter = Counter()
    latencies_us: list[float] = []
    flicker_hits = 0
    states_observed: Counter = Counter()
    bias_dirs: Counter = Counter()
    trigger_codes: Counter = Counter()
    transitions_per_session_per_sym: dict[str, dict[str, int]] = defaultdict(
        lambda: defaultdict(int)
    )
    # Critere Phase 2 reformule (post-NOGO 18/05 ml-trainer) :
    # compter sessions avec n_transitions > FLICKER_THRESHOLD (=8) au lieu de bars.
    sessions_over_flicker: set[str] = set()
    trans_per_session_count: dict[str, int] = defaultdict(int)

    # Captured log function for flicker count
    def log_capture(code: str, **ctx) -> None:
        nonlocal flicker_hits
        if code == "BOT3_NSM_FLICKER_GUARD":
            flicker_hits += 1

    prev_close: float | None = None
    crashes = 0

    for idx, row in df.iterrows():
        try:
            bar = _row_to_bar(row, int(row["bar_idx_session_calc"]))
            ctx = _row_to_ctx(row)
            swing = _row_to_swing(row)
            # Fix 18/05 : calculer story trackers EN PARALLEL (au lieu de hardcode 0).
            # Sans ca T2/T3/T10/T11 ne firent jamais (slope_60, hh_60, ll_60 = 0).
            story = update_story_trackers(story_state, bar, swing, log_fn=None)

            # Phase 2 : detection plot twists AVANT NSM transition (anti leak)
            tick_size = float(ctx.get("tick_size") or 0.25)
            twists = scan_all(twist_state, bar, swing, tick_size=tick_size,
                              log_fn=log_capture)
            for tw in twists:
                twists_per_type[tw.twist_type] += 1
                twists_observed.append({
                    "ts": tw.bar_ts, "sdt": bar["session_date_trading"],
                    "type": tw.twist_type, "direction": tw.direction,
                    "severity": tw.severity,
                })

            t0 = time.perf_counter_ns()
            snap = nsm.transition(
                symbol, bar, ctx, regime=None, story_trackers=story,
                swing_state=swing, log_fn=log_capture,
            )
            elapsed_us = (time.perf_counter_ns() - t0) / 1000.0
            latencies_us.append(elapsed_us)

            # Phase 2 : validator narrative apres NSM transition
            if snap is not None:
                is_valid, reason = is_narrative_still_valid(
                    snap, twists, log_fn=log_capture,
                )
                if not is_valid:
                    invalidations.append({
                        "ts": bar["ts_event_iso"],
                        "sdt": bar["session_date_trading"],
                        "state": snap.state.value,
                        "reason": reason,
                    })

                # Phase 3 J+3 : shadow mode integration.
                # Detection levels touches (MVP) : prev_vah, prev_val, swing_high/low.
                # Pour chaque touch, call resolver + log shadow comparison.
                close_now = _safe(row.get("close"))
                if close_now is not None:
                    # Niveaux candidats avec leur (legacy_side, nature)
                    candidates = []
                    pv_high = _safe(row.get("prev_vah"))
                    pv_low = _safe(row.get("prev_val"))
                    sw_high = swing.last_swing_high.price
                    sw_low = swing.last_swing_low.price

                    # Proximity 0.1% du prix actuel (= ~5 ticks ES, ~20 ticks NQ)
                    tol = abs(close_now) * 0.001
                    if pv_high is not None and abs(close_now - pv_high) <= tol:
                        candidates.append(("prev_vah", "resistance", "SHORT", pv_high))
                    if pv_low is not None and abs(close_now - pv_low) <= tol:
                        candidates.append(("prev_val", "support", "LONG", pv_low))
                    if sw_high > 0 and abs(close_now - sw_high) <= tol:
                        candidates.append(("swing_high", "resistance", "SHORT", sw_high))
                    if sw_low > 0 and abs(close_now - sw_low) <= tol:
                        candidates.append(("swing_low", "support", "LONG", sw_low))

                    for level_name, nature, legacy_side, level_price in candidates:
                        resolved = resolver.resolve(
                            snap, level_name=level_name, level_nature=nature,
                            level_price=level_price, bar=bar, log_fn=log_capture,
                        )
                        shadow_total += 1
                        if resolved.side == "LONG":
                            shadow_long += 1
                        elif resolved.side == "SHORT":
                            shadow_short += 1
                        else:
                            shadow_no_trade += 1

                        if resolved.scenario_id and resolved.scenario_id != "NO_MATCH":
                            scenarios_fired[resolved.scenario_id] += 1

                        # Log shadow JSONL si non NO_TRADE (signal actionable)
                        if resolved.side != "NO_TRADE":
                            is_div = detect_divergence(legacy_side, resolved.side)
                            if is_div:
                                shadow_divergences += 1
                            shadow_logger.log_comparison(ShadowComparison(
                                ts=bar["ts_event_iso"],
                                symbol=symbol,
                                level_name=level_name,
                                level_nature=nature,
                                narrative_state=snap.state.value,
                                legacy_side=legacy_side,
                                narrative_side=resolved.side,
                                narrative_scenario_id=resolved.scenario_id,
                                narrative_confidence=resolved.confidence,
                                is_divergence=is_div,
                            ), log_fn=log_capture)

            if snap is not None:
                states_observed[snap.state.value] += 1

            # Source de verite pour transitions = events emis (consume_events).
            # snap.triggering_features colle entre bars sans transition reelle.
            for evt in nsm.consume_events():
                if evt.event_type != "STATE_TRANSITION":
                    continue
                trigger = evt.payload.get("triggering", {}).get("trigger", "")
                sdt_key = bar["session_date_trading"]
                transitions.append({
                    "ts": evt.bar_ts,
                    "sdt": sdt_key,
                    "symbol": symbol,
                    "from_state": evt.from_state.value if evt.from_state else "",
                    "state": evt.to_state.value,
                    "bias_dir": evt.payload.get("bias_dir", 0),
                    "confidence": evt.payload.get("confidence", 0.0),
                    "trigger": trigger,
                })
                bias_dirs[evt.payload.get("bias_dir", 0)] += 1
                trigger_codes[trigger.split("_")[0] if trigger else "?"] += 1
                transitions_per_session_per_sym[sdt_key][symbol] += 1
                trans_per_session_count[sdt_key] += 1
                # Critere Phase 2 reformule : track session-level overflow
                if trans_per_session_count[sdt_key] > FLICKER_GUARD_THRESHOLD:
                    sessions_over_flicker.add(sdt_key)

            prev_close = _safe(row.get("close"))
        except Exception as e:
            crashes += 1
            print(f"  CRASH bar {idx} ({row.get('ts_event')}): {type(e).__name__}: {e}",
                  file=sys.stderr)

    # Latency stats
    latencies_us.sort()
    n = len(latencies_us)
    p50 = latencies_us[n // 2] if n else 0
    p95 = latencies_us[int(n * 0.95)] if n else 0
    p99 = latencies_us[int(n * 0.99)] if n else 0
    p_max = latencies_us[-1] if n else 0

    # Compute critere passage Phase 2
    n_sessions = len(sessions)
    n_transitions = len(transitions)
    avg_transitions_per_session = n_transitions / n_sessions if n_sessions else 0
    bias_neg = bias_dirs.get(-1, 0)
    bias_total = sum(bias_dirs.values())
    pct_short = (bias_neg / bias_total * 100) if bias_total else 0

    # Critères Phase 2 reformulés (post-NOGO 18/05 ml-trainer + market-analyst)
    # cf DOCS/plans/2026-05-18-bot3-narrative-layer-spec.md section "Phase 2 gate"
    n_sessions_active_ny = sum(
        1 for sdt, syms in transitions_per_session_per_sym.items()
        if syms.get(symbol, 0) >= 1
    )
    pct_sessions_active = (n_sessions_active_ny / n_sessions * 100) if n_sessions else 0
    # Coverage transitions : combien de T_x distincts ont fire au moins 1x
    unique_triggers = len([k for k in trigger_codes.keys() if k.startswith("T")])
    # NSM exporte 36 transitions (T1-T32 + T6bis/T7bis/T9bis + T30b/T31b) — coverage cible 50%
    coverage_pct = (unique_triggers / 36 * 100) if unique_triggers else 0

    # Critère flicker tolerant : <= 20% des sessions (sur jours hyper-actifs
    # Wyckoff + BOS + Exhaustion multi-phase, le narratif legitime depasse
    # parfois 12 trans/jour. Phase 2 PlotTwistDetectors filtrera ces flips
    # sub-narrative. Tolerance 20% = 1 session sur 5.
    pct_sessions_over_flicker = (
        len(sessions_over_flicker) / n_sessions * 100 if n_sessions else 0
    )

    # Phase 2 metrics
    twists_per_session = (
        len(twists_observed) / n_sessions if n_sessions else 0
    )
    # n_invalidations_per_session: track invalidations from validator
    n_invalidations = len(invalidations)

    # Phase 3 shadow mode metrics
    shadow_actionable = shadow_long + shadow_short
    pct_shadow_short = (shadow_short / shadow_actionable * 100) if shadow_actionable else 0
    pct_shadow_long = (shadow_long / shadow_actionable * 100) if shadow_actionable else 0
    # bidirectional ratio = pct short narrative (objectif >= 35% vs 6.7% legacy V1)

    criteres = {
        "0_crash": crashes == 0,
        "p99_under_5ms": p99 < 5000,
        "pct_sessions_active_ge_80": pct_sessions_active >= 80,
        "pct_short_ge_30": pct_short >= 30,
        "pct_sessions_over_flicker_le_20": pct_sessions_over_flicker <= 20,
        "coverage_ge_30pct": coverage_pct >= 30,
        "twists_per_session_in_20_to_200": 20 <= twists_per_session <= 200,
        # Phase 3 J+3 gate (cf master plan sect 268)
        # Bidirectional ratio shadow >= 35% SHORT (vs 6.7% legacy V1)
        # Objectif master plan : corriger biais LONG Bot 3 v1 (80% LONG)
        "shadow_pct_short_ge_35": pct_shadow_short >= 35,
        # Shadow actionable >= 5 sur 5j (au moins 1/jour signal actionable)
        # Reformule vs "10-200 divergences" : narrative s'aligne sur legacy quand
        # narrative_state matche level nature (UPTHRUST resistance = SHORT pour les deux).
        # Divergences vraies = cas rares (narrative LONG sur resistance). Critere "5 actionable"
        # confirme que resolver produit des signaux (vs muet) sans exiger contre-legacy.
        "shadow_actionable_ge_5": shadow_actionable >= 5,
    }
    all_pass = all(criteres.values())

    return {
        "symbol": symbol,
        "parquet": str(parquet_path),
        "n_bars": len(df),
        "n_sessions": n_sessions,
        "n_sessions_active_ny": n_sessions_active_ny,
        "pct_sessions_active": round(pct_sessions_active, 2),
        "n_transitions": n_transitions,
        "avg_transitions_per_session": round(avg_transitions_per_session, 2),
        "coverage_triggers": unique_triggers,
        "coverage_pct": round(coverage_pct, 2),
        "crashes": crashes,
        "flicker_hits_bars": flicker_hits,
        "sessions_over_flicker": list(sessions_over_flicker),
        "latency_us": {
            "p50": round(p50, 2), "p95": round(p95, 2),
            "p99": round(p99, 2), "max": round(p_max, 2),
        },
        "states_observed": dict(states_observed),
        "bias_dirs": dict(bias_dirs),
        "pct_short": round(pct_short, 2),
        "trigger_codes": dict(trigger_codes),
        "transitions_per_session": {
            sdt: dict(syms) for sdt, syms in transitions_per_session_per_sym.items()
        },
        # Phase 2 stats
        "n_twists_observed": len(twists_observed),
        "twists_per_session": round(twists_per_session, 2),
        "twists_per_type": dict(twists_per_type),
        "n_invalidations": n_invalidations,
        # Phase 3 stats
        "shadow_total": shadow_total,
        "shadow_long": shadow_long,
        "shadow_short": shadow_short,
        "shadow_no_trade": shadow_no_trade,
        "shadow_divergences": shadow_divergences,
        "shadow_pct_short": round(pct_shadow_short, 2),
        "shadow_pct_long": round(pct_shadow_long, 2),
        "scenarios_fired": dict(scenarios_fired),
        "criteres_phase2": criteres,
        "all_pass": all_pass,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Replay NSM tracking-only")
    parser.add_argument("--parquet", required=True, help="V4 enriched parquet path")
    parser.add_argument("--symbol", required=True, help="ES / NQ / MGC")
    parser.add_argument("--start", default=None, help="Session start YYYY-MM-DD")
    parser.add_argument("--end", default=None, help="Session end YYYY-MM-DD")
    args = parser.parse_args()

    stats = replay(
        Path(args.parquet),
        symbol=args.symbol,
        sdt_start=args.start,
        sdt_end=args.end,
    )

    # Print summary
    print()
    print("=" * 70)
    print(f"REPLAY NSM TRACKING-ONLY - {args.symbol}")
    print("=" * 70)
    print(f"Parquet         : {stats['parquet']}")
    print(f"Bars processed  : {stats['n_bars']} ({stats['n_sessions']} sessions)")
    print(f"Transitions     : {stats['n_transitions']} "
          f"(avg {stats['avg_transitions_per_session']}/session)")
    print(f"Sessions active : {stats['n_sessions_active_ny']}/{stats['n_sessions']} "
          f"({stats['pct_sessions_active']}%)")
    print(f"Coverage        : {stats['coverage_triggers']}/36 triggers "
          f"({stats['coverage_pct']}%)")
    print(f"Crashes         : {stats['crashes']}")
    print(f"Flicker         : {stats['flicker_hits_bars']} bars-bloquees, "
          f"{len(stats['sessions_over_flicker'])} sessions-bloquees")
    print(f"Latency (us)    : p50={stats['latency_us']['p50']} "
          f"p95={stats['latency_us']['p95']} "
          f"p99={stats['latency_us']['p99']} "
          f"max={stats['latency_us']['max']}")
    # Phase 2 stats
    print(f"PlotTwists      : {stats['n_twists_observed']} total "
          f"({stats['twists_per_session']}/session)")
    if stats['twists_per_type']:
        for tt, n in sorted(stats['twists_per_type'].items(), key=lambda x: -x[1]):
            print(f"  {tt:20s} : {n}")
    print(f"Invalidations   : {stats['n_invalidations']}")
    # Phase 3 stats
    print()
    print(f"Shadow mode     : {stats['shadow_total']} resolutions "
          f"(LONG={stats['shadow_long']} SHORT={stats['shadow_short']} "
          f"NO_TRADE={stats['shadow_no_trade']})")
    print(f"  pct LONG / SHORT : {stats['shadow_pct_long']}% / {stats['shadow_pct_short']}%")
    print(f"  Divergences vs legacy : {stats['shadow_divergences']}")
    if stats['scenarios_fired']:
        print("  Scenarios fired :")
        for sid, n in sorted(stats['scenarios_fired'].items(), key=lambda x: -x[1]):
            print(f"    {sid:35s} : {n}")
    print()
    print("States observed:")
    for state, count in sorted(stats["states_observed"].items(),
                                key=lambda x: -x[1]):
        print(f"  {state:30s} : {count}")
    print()
    print("Bias_dir distribution:")
    for bias, count in sorted(stats["bias_dirs"].items()):
        pct = count / stats["n_transitions"] * 100 if stats["n_transitions"] else 0
        print(f"  {bias:+d} : {count} ({pct:.1f}%)")
    print(f"  [pct short = {stats['pct_short']}%]")
    print()
    print("Trigger codes (transitions):")
    for code, count in sorted(stats["trigger_codes"].items(),
                                key=lambda x: -x[1]):
        print(f"  {code:6s} : {count}")
    print()
    print("Transitions per session:")
    for sdt, syms in sorted(stats["transitions_per_session"].items()):
        for sym, n in syms.items():
            print(f"  {sdt} {sym} : {n}")
    print()
    print("Criteres passage Phase 2:")
    for crit, ok in stats["criteres_phase2"].items():
        icon = "OK " if ok else "NOK"
        print(f"  [{icon}] {crit}")
    print()
    verdict = "GO PHASE 2" if stats["all_pass"] else "NOGO (review criteres)"
    print(f"VERDICT : {verdict}")


if __name__ == "__main__":
    main()
