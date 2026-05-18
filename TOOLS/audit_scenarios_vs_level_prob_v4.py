"""Audit empirique scenarios DirectionResolver (S01-S10) vs LEVEL_PROB_V4.

Pivot mandate (Jackson 18/05) : remplacer le backtest in-house 89 trades (0 EDGE)
par une mise en correspondance avec le backtest existant de Claude 4.7 qui teste
55 niveaux x multiples contextes sur 318 jours (April 2025 - May 2026), ~700K barres.

Sources :
    DOCS/LEVEL_PROB_V4_NQ.md (356K bars NQ.c.0, proximity 0.05%)
    DOCS/LEVEL_PROB_V4_ES.md (357K bars ES.c.0, proximity 0.08%)

Mapping :
    Scenario (NarrativeState, level_nature) -> liste candidate (level, ctx)
    qui doivent exister empiriquement dans LEVEL_PROB_V4.

Verdict par scenario (S01..S10) :
    VALIDATED  : >=1 level mapped a PF baseline >= 1.30 (ou >=2.0 avec context)
    MARGINAL   : >=1 level mapped a PF in [1.10, 1.30)
    NO_EDGE    : tous les levels mapped a PF < 1.10
    NO_DATA    : aucun level mapped (gap mapping)

Usage : python -X utf8 tools/audit_scenarios_vs_level_prob_v4.py
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DOC_NQ = ROOT / "DOCS" / "LEVEL_PROB_V4_NQ.md"
DOC_ES = ROOT / "DOCS" / "LEVEL_PROB_V4_ES.md"
OUT_JSON = ROOT / "DOCS" / "AUDIT_SCENARIOS_VS_LEVEL_PROB_V4.json"
OUT_MD = ROOT / "DOCS" / "AUDIT_SCENARIOS_VS_LEVEL_PROB_V4.md"

PF_VALIDATED = 1.30
PF_MARGINAL = 1.10
PF_CONTEXT_BOOST = 2.00
N_MIN = 30


@dataclass
class LevelRow:
    """Une ligne du ranking section 1 LEVEL_PROB_V4."""

    name: str
    group: str
    n: int
    rej_pct: float
    pf: float
    avg_move_ticks: float
    best_rej_ctx: str | None
    best_rej_pf: float | None
    best_acc_ctx: str | None
    best_acc_pf: float | None
    symbol: str  # "ES" / "NQ"
    # Enrichi via section 2 : top contextes pro-rejection (dim, value, N, rej%, PF)
    ctx_rows: list[dict[str, Any]] = field(default_factory=list)
    # Enrichi via section 3 : si ce level apparait dans top 10 setups niveau+ctx
    top_setups: list[dict[str, Any]] = field(default_factory=list)


def _parse_float(v: str) -> float | None:
    v = v.strip()
    if v in ("-", "", "—"):
        return None
    try:
        return float(v.replace("t", "").replace("%", "").replace("pp", "").replace("+", ""))
    except ValueError:
        return None


def _parse_int(v: str) -> int:
    return int(v.strip().replace(",", ""))


def parse_level_prob_v4(path: Path, symbol: str) -> list[LevelRow]:
    """Parse section 1 RANKING + section 2 DETAIL (top contextes pro-rejection)."""

    text = path.read_text(encoding="utf-8")
    lines = text.split("\n")
    rows: list[LevelRow] = []
    # ─── Pass 1 : section 1 ────────────────────────────────────────────
    in_section_1 = False
    for line in lines:
        if line.startswith("## 1. RANKING"):
            in_section_1 = True
            continue
        if line.startswith("## 2."):
            break
        if not in_section_1:
            continue
        if not line.startswith("|"):
            continue
        if line.startswith("| Niveau") or line.startswith("|---"):
            continue
        cols = [c.strip() for c in line.split("|")]
        if len(cols) < 12:
            continue
        try:
            row = LevelRow(
                name=cols[1],
                group=cols[2],
                n=_parse_int(cols[3]),
                rej_pct=float(cols[4].replace("%", "")),
                pf=float(cols[5]),
                avg_move_ticks=_parse_float(cols[6]) or 0.0,
                best_rej_ctx=cols[7] if cols[7] not in ("-", "—") else None,
                best_rej_pf=_parse_float(cols[8]),
                best_acc_ctx=cols[9] if cols[9] not in ("-", "—") else None,
                best_acc_pf=_parse_float(cols[10]),
                symbol=symbol,
            )
            rows.append(row)
        except (ValueError, IndexError) as exc:
            print(f"  [skip] {symbol} line: {line[:80]}... ({exc})")
            continue

    # ─── Pass 2 : section 2 — top contextes par level ─────────────────
    rows_by_name: dict[str, LevelRow] = {r.name: r for r in rows}

    # ─── Pass 3 : section 3 SYNTHESE TOP 10 SETUPS (sera ajoute apres) ──
    # Fait en parallele a la fin pour ne pas casser la structure des blocks

    current_level: LevelRow | None = None
    in_section_2 = False
    in_pro_rej_block = False
    in_session_block = False
    header_seen = False

    for line in lines:
        if line.startswith("## 2. DETAIL"):
            in_section_2 = True
            continue
        if line.startswith("## 3.") or line.startswith("## 4."):
            break
        if not in_section_2:
            continue

        # Header level "### NAME — desc..."
        m = re.match(r"^###\s+([A-Z0-9_]+)\s*—", line)
        if m:
            current_level = rows_by_name.get(m.group(1))
            in_pro_rej_block = False
            in_session_block = False
            header_seen = False
            continue

        if current_level is None:
            continue

        if "PRO-REJECTION" in line:
            in_pro_rej_block = True
            in_session_block = False
            header_seen = False
            continue
        if "PRO-ACCEPTANCE" in line:
            in_pro_rej_block = False
            in_session_block = False
            continue
        if "Par session" in line:
            in_pro_rej_block = False
            in_session_block = True
            header_seen = False
            continue

        if not (in_pro_rej_block or in_session_block):
            continue
        if not line.startswith("|"):
            continue
        # Skip header rows (first 2 markdown table lines)
        if line.startswith("|---"):
            header_seen = True
            continue
        if not header_seen:
            # First non-separator line after block header is the column header row
            header_seen = False  # reset for next iter
            continue

        cols = [c.strip() for c in line.split("|")]
        # Pro-rej : | Dimension | Value | N | Rejection % | Edge | PF |
        if in_pro_rej_block and len(cols) >= 7:
            try:
                dim = cols[1]
                value = cols[2]
                n = _parse_int(cols[3])
                rej = float(cols[4].replace("%", ""))
                edge = _parse_float(cols[5]) or 0.0
                pf = float(cols[6])
                current_level.ctx_rows.append(
                    {"dim": dim, "value": value, "n": n, "rej_pct": rej,
                     "edge_pp": edge, "pf": pf, "kind": "PRO_REJECTION"}
                )
            except (ValueError, IndexError):
                continue
        # Session : | Session | N | Rejection % | PF |
        elif in_session_block and len(cols) >= 5:
            try:
                sess = cols[1]
                n = _parse_int(cols[2])
                rej = float(cols[3].replace("%", ""))
                pf = float(cols[4])
                current_level.ctx_rows.append(
                    {"dim": "session", "value": sess, "n": n, "rej_pct": rej,
                     "edge_pp": None, "pf": pf, "kind": "SESSION"}
                )
            except (ValueError, IndexError):
                continue

    # ─── Pass 3 : section 3 SYNTHESE TOP 10 SETUPS ─────────────────────
    in_section_3 = False
    s3_header_seen = False
    for line in lines:
        if line.startswith("## 3."):
            in_section_3 = True
            s3_header_seen = False
            continue
        if line.startswith("## 4.") or line.startswith("## 5."):
            break
        if not in_section_3:
            continue
        if not line.startswith("|"):
            continue
        if line.startswith("|---"):
            s3_header_seen = True
            continue
        if line.startswith("| #"):
            continue
        if not s3_header_seen:
            continue
        cols = [c.strip() for c in line.split("|")]
        if len(cols) < 10:
            continue
        try:
            level_field = cols[3]
            level_name = level_field.split(" ")[0].strip()
            row = rows_by_name.get(level_name)
            if row is None:
                continue
            setup = {
                "rank": int(cols[1]),
                "type": cols[2],
                "context": cols[4],
                "n": _parse_int(cols[5]),
                "rej_pct": float(cols[6].replace("%", "")),
                "edge_pp": _parse_float(cols[7]) or 0.0,
                "pf": float(cols[8]),
            }
            row.top_setups.append(setup)
        except (ValueError, IndexError):
            continue

    return rows


# ─────────────────────────────────────────────────────────────────────
# Mapping scenario -> (level_nature, levels candidates, context filter)
# ─────────────────────────────────────────────────────────────────────
# level_nature -> set de levels candidates dans LEVEL_PROB_V4.
# Categorisation revisee 18/05 apres findings section 3 :
#   - TRAPPED_SELL = vendeurs pieges (rejection = LONG) -> SUPPORT
#   - TRAPPED_BUY  = acheteurs pieges (rejection = SHORT) -> RESISTANCE
#   - EDGE_BUY_Z   = setup bullish -> SUPPORT
#   - EDGE_SELL_Z  = setup bearish -> RESISTANCE
#   - DELTA_DIV_BUY = divergence acheteuse (rejection = LONG) -> SUPPORT
#   - DELTA_DIV_SELL = divergence vendeuse (rejection = SHORT) -> RESISTANCE
#   - CLUSTER_UP  = cluster en haut (= resistance) -> RESISTANCE
#   - CLUSTER_DN  = cluster en bas (= support) -> SUPPORT
#   - COLOR_UP/DN, OPEN_*, SINGLE_PRINT, NAKED_POC, VPOC, MQ_HVL, SPIKE/SP_ZONE = symetrique -> STRUCTURAL
SUPPORT_LEVELS = {
    "IB_LOW", "MQ_PUT_0DTE", "MQ_PUT", "GEX_DN",
    "PVAL", "PDL", "CUR_VAL",
    "VWAP_SD1D", "VWAP_SD2D", "PVWAP_SD1D",
    "ASIA_LOW", "LONDON_LOW", "SWING_LOW", "OVN_LOW",
    "CASH_LOW", "SESS_LOW",
    "MQ_1D_MIN",
    # Setups directionnels bullish
    "TRAPPED_SELL", "EDGE_BUY_Z", "DELTA_DIV_BUY", "CLUSTER_DN",
}
RESISTANCE_LEVELS = {
    "IB_HIGH", "MQ_CALL_0DTE", "MQ_CALL", "GEX_UP",
    "PVAH", "PDH", "CUR_VAH",
    "VWAP_SD1U", "VWAP_SD2U", "PVWAP_SD1U",
    "ASIA_HIGH", "LONDON_HIGH", "SWING_HIGH", "OVN_HIGH",
    "CASH_HIGH", "SESS_HIGH",
    "MQ_1D_MAX",
    # Setups directionnels bearish
    "TRAPPED_BUY", "EDGE_SELL_Z", "DELTA_DIV_SELL", "CLUSTER_UP",
}
STRUCTURAL_LEVELS = {
    "SINGLE_PRINT", "NAKED_POC", "MQ_HVL", "CUR_VPOC", "PVPOC",
    "SPIKE_ORIGIN", "SP_ZONE",
    "COLOR_UP", "COLOR_DN",  # zones BN extensions, peuvent etre support OU resistance
    "VWAP_D", "PVWAP",
    "OPEN_830", "OPEN_930",
}


@dataclass
class ScenarioSpec:
    """Spec d'un scenario S01..S10."""

    scenario_id: str
    narrative_state: str  # ex "OPEN_DRIVE_UP"
    level_nature: str  # "support"/"resistance"/"structural"
    side: str  # "LONG"/"SHORT"
    # Contexte LEVEL_PROB_V4 attendu (clef de col best_rej_ctx).
    # Ex : "open_type=T0" pour OD, "day_type=T1" pour Trend day.
    expected_ctx_keys: list[str] = field(default_factory=list)
    canon: str = ""


# Mapping narrative_state -> filtre contexte LEVEL_PROB_V4 (best_rej_ctx col).
# Reference : game_changers.py OpenType IntEnum + DTRC day_type.
# T0=OD, T1=OTD, T2=OAOR, T3=OAIR + day_type T1=Trend, T2=Double Dist Trend,
# T3=Double Dist Range, T4=Normal Variation, T5=Normal Day, T6=Trend Variation.
SCENARIOS: list[ScenarioSpec] = [
    ScenarioSpec(
        scenario_id="S01_OD_UP_support_bounce",
        narrative_state="OPEN_DRIVE_UP",
        level_nature="support",
        side="LONG",
        expected_ctx_keys=["open_type=T0"],
        canon="Dalton MOM Ch.7 — Open Drive momentum continuation",
    ),
    ScenarioSpec(
        scenario_id="S02_OD_DOWN_resistance_rejection",
        narrative_state="OPEN_DRIVE_DOWN",
        level_nature="resistance",
        side="SHORT",
        expected_ctx_keys=["open_type=T0"],
        canon="Dalton MOM Ch.7 — Open Drive momentum continuation",
    ),
    ScenarioSpec(
        scenario_id="S03_TREND_UP_support_pullback",
        narrative_state="TREND_UP_CONTINUATION",
        level_nature="support",
        side="LONG",
        expected_ctx_keys=["day_type=T1"],
        canon="Dalton MOM Ch.10 Trend Day pullback entry",
    ),
    ScenarioSpec(
        scenario_id="S04_TREND_DOWN_resistance_pullback",
        narrative_state="TREND_DOWN_CONTINUATION",
        level_nature="resistance",
        side="SHORT",
        # day_type=T1 (Trend Day), T2 (Double Dist Trend), T6 (Trend Variation).
        # PAS de proxy open_type (OD/OTD sont des opens initiaux, pas une trend
        # continuation = data fishing).
        # NOTE : dataset histo avril 2025-mai 2026 = BULLISH majoritaire => les Trend Days
        # mesures sont surtout UP, donc resistances rejettent peu en day_type=T1.
        # Asymetrie statistique biais histo.
        expected_ctx_keys=["day_type=T1", "day_type=T2", "day_type=T6"],
        canon="Dalton MOM Ch.10 Trend Day pullback entry (biais histo bullish limite mesure)",
    ),
    ScenarioSpec(
        scenario_id="S05_SPRING_recovery_long",
        narrative_state="WYCKOFF_SPRING_LONG",
        level_nature="support",
        side="LONG",
        expected_ctx_keys=[],  # rare event Wyckoff, pas de dim direct
        canon="Wyckoff Phase C Spring (Pruden Three Skills Ch.7)",
    ),
    ScenarioSpec(
        scenario_id="S06_UPTHRUST_rejection_short",
        narrative_state="WYCKOFF_UPTHRUST_SHORT",
        level_nature="resistance",
        side="SHORT",
        expected_ctx_keys=[],  # rare event Wyckoff
        canon="Wyckoff Phase C Upthrust (Pruden Three Skills Ch.7)",
    ),
    ScenarioSpec(
        scenario_id="S07_RANGE_support_long",
        narrative_state="RANGE_RESPECTED",
        level_nature="support",
        side="LONG",
        # Proxies RANGE day : day_type=T3 (DD Range), T4 (Normal Variation),
        # T5 (Normal Day = balanced). open_type=T2 (OAOR) ou T3 (OAIR) = range open.
        # va_dev=STABLE = Value Area stable (range signature).
        expected_ctx_keys=["day_type=T3", "day_type=T4", "day_type=T5",
                           "open_type=T2", "open_type=T3", "va_dev=STABLE"],
        canon="Dalton MOM Ch.9 Range Day fade",
    ),
    ScenarioSpec(
        scenario_id="S08_RANGE_resistance_short",
        narrative_state="RANGE_RESPECTED",
        level_nature="resistance",
        side="SHORT",
        expected_ctx_keys=["day_type=T3", "day_type=T4", "day_type=T5",
                           "open_type=T2", "open_type=T3", "va_dev=STABLE"],
        canon="Dalton MOM Ch.9 Range Day fade",
    ),
    ScenarioSpec(
        scenario_id="S09_EXHAUSTION_TOP_short",
        narrative_state="EXHAUSTION_TOP",
        level_nature="resistance",
        side="SHORT",
        expected_ctx_keys=["cvd_trend=FLAT", "range_pos=TOP"],
        canon="Wyckoff buying climax (Pruden Ch.7)",
    ),
    ScenarioSpec(
        scenario_id="S10_EXHAUSTION_BOTTOM_long",
        narrative_state="EXHAUSTION_BOTTOM",
        level_nature="support",
        side="LONG",
        expected_ctx_keys=["cvd_trend=FLAT", "range_pos=BOT"],
        canon="Wyckoff selling climax (Pruden Ch.7)",
    ),
]


def _levels_for_nature(nature: str) -> set[str]:
    if nature == "support":
        return SUPPORT_LEVELS
    if nature == "resistance":
        return RESISTANCE_LEVELS
    if nature == "structural":
        return STRUCTURAL_LEVELS
    return set()


def _ctx_matches(ctx: str | None, expected_keys: list[str]) -> bool:
    """Match si le ctx (string ou 'dim=value') contient une des clefs attendues."""

    if not ctx or not expected_keys:
        return False
    for key in expected_keys:
        if key in ctx:
            return True
    return False


def _ctx_row_matches(row: dict, expected_keys: list[str]) -> bool:
    """Check si une ctx_row (dim, value) matche un expected_key 'dim=value'."""

    if not expected_keys:
        return False
    candidate = f"{row['dim']}={row['value']}"
    for key in expected_keys:
        if key == candidate or key in candidate:
            return True
    return False


def audit_scenario(spec: ScenarioSpec, rows_es: list[LevelRow], rows_nq: list[LevelRow]) -> dict:
    """Calcule le verdict empirique STRICT d'un scenario.

    Mode strict :
    - Si scenario a expected_ctx_keys non-vide : il FAUT >=1 level avec
      best_rej_ctx matchant l'un des keys ET best_rej_pf >= PF_MARGINAL.
      Sinon -> NO_EMPIRICAL_CTX (l'edge baseline ne valide PAS le scenario,
      seul l'edge contextuel est interpretable).
    - Si scenario rare event (Wyckoff, expected_ctx_keys vide) : LEVEL_PROB_V4
      ne mesure pas le contexte rare -> NO_EMPIRICAL_DIM (incertain, requiert
      backtest dedie).
    - On loggue aussi les baseline matches comme INFO (borne sup), pas comme
      verdict positif. Cf docstring header pivot mandate.
    """

    candidates = _levels_for_nature(spec.level_nature)
    baseline_hits: list[dict[str, Any]] = []
    ctx_hits: list[dict[str, Any]] = []

    for rows in (rows_nq, rows_es):
        for r in rows:
            if r.name not in candidates:
                continue
            baseline_ok = r.pf >= PF_MARGINAL and r.n >= N_MIN
            # 1. Check section 1 best_rej_ctx
            best_rej_ctx_ok = (
                r.best_rej_pf is not None
                and r.best_rej_pf >= PF_MARGINAL
                and _ctx_matches(r.best_rej_ctx, spec.expected_ctx_keys)
            )
            # 2. Check section 2 ctx_rows pour matches plus profonds
            section2_matches = []
            for cr in r.ctx_rows:
                if cr["kind"] != "PRO_REJECTION":
                    continue
                if not _ctx_row_matches(cr, spec.expected_ctx_keys):
                    continue
                if cr["n"] < N_MIN:
                    continue
                if cr["pf"] < PF_MARGINAL:
                    continue
                section2_matches.append(cr)
            # 3. Check section 3 top setups (preuve la plus forte)
            section3_matches = []
            for ts in r.top_setups:
                if ts["type"] != "REJECTION":
                    continue
                if not _ctx_matches(ts["context"], spec.expected_ctx_keys):
                    continue
                if ts["n"] < N_MIN:
                    continue
                if ts["pf"] < PF_MARGINAL:
                    continue
                section3_matches.append(ts)
            ctx_ok = (
                best_rej_ctx_ok or bool(section2_matches) or bool(section3_matches)
            )
            # Choisir la "best" ctx evidence (section1 vs section2 vs section3)
            best_ctx_pf: float | None = None
            best_ctx_label: str | None = None
            best_ctx_n: int | None = None
            best_ctx_source: str = ""
            if best_rej_ctx_ok:
                best_ctx_pf = r.best_rej_pf
                best_ctx_label = r.best_rej_ctx
                best_ctx_n = None
                best_ctx_source = "section1"
            for cr in section2_matches:
                if best_ctx_pf is None or cr["pf"] > best_ctx_pf:
                    best_ctx_pf = cr["pf"]
                    best_ctx_label = f"{cr['dim']}={cr['value']}"
                    best_ctx_n = cr["n"]
                    best_ctx_source = "section2"
            for ts in section3_matches:
                if best_ctx_pf is None or ts["pf"] > best_ctx_pf:
                    best_ctx_pf = ts["pf"]
                    best_ctx_label = ts["context"]
                    best_ctx_n = ts["n"]
                    best_ctx_source = f"section3_top{ts['rank']}"
            entry = {
                "symbol": r.symbol,
                "level": r.name,
                "n": r.n,
                "rej_pct": r.rej_pct,
                "pf_baseline": r.pf,
                "best_rej_ctx": r.best_rej_ctx,
                "best_rej_pf": r.best_rej_pf,
                "best_ctx_pf": best_ctx_pf,
                "best_ctx_label": best_ctx_label,
                "best_ctx_n": best_ctx_n,
                "best_ctx_source": best_ctx_source,
                "section2_matches_count": len(section2_matches),
                "section3_matches_count": len(section3_matches),
                "baseline_ok": baseline_ok,
                "ctx_ok": ctx_ok,
            }
            if ctx_ok:
                ctx_hits.append(entry)
            if baseline_ok and not ctx_ok:
                baseline_hits.append(entry)

    # ─── Verdict STRICT ────────────────────────────────────────────────
    # Wyckoff / rare events : LEVEL_PROB_V4 ne mesure pas la dim
    if not spec.expected_ctx_keys:
        verdict = "NO_EMPIRICAL_DIM"
        reason = (
            "Scenario rare event (Wyckoff Spring/Upthrust, exhaustion sans ctx). "
            "LEVEL_PROB_V4 ne fournit pas de dimension contextuelle dediee — "
            "validation requiert backtest event-detection sur swing pivots."
        )
    elif ctx_hits:
        ctx_hits.sort(key=lambda m: m["best_ctx_pf"] or 0.0, reverse=True)
        top = ctx_hits[0]
        top_pf = top["best_ctx_pf"] or 0.0
        if top_pf >= PF_CONTEXT_BOOST * 2.0:
            verdict = "VALIDATED_STRONG"
        elif top_pf >= PF_CONTEXT_BOOST:
            verdict = "VALIDATED"
        elif top_pf >= PF_VALIDATED:
            verdict = "VALIDATED_WEAK"
        else:
            verdict = "MARGINAL_CTX"
        reason = (
            f"{len(ctx_hits)} level(s) avec context match. "
            f"top_ctx_pf={top_pf:.2f} sur {top['symbol']}:{top['level']} "
            f"({top['best_ctx_label']})"
        )
    elif baseline_hits:
        # Pas de ctx match -> incertain. La baseline ne prouve PAS le scenario.
        verdict = "NO_EMPIRICAL_CTX"
        reason = (
            f"Aucun level avec best_rej_ctx match expected={spec.expected_ctx_keys}. "
            f"{len(baseline_hits)} level(s) ont une baseline PF>=1.10 (borne sup, "
            "pas une preuve scenario)."
        )
    else:
        verdict = "NO_EDGE"
        reason = "Aucun level ni context ni baseline >= 1.10."

    matches = ctx_hits + baseline_hits

    return {
        "scenario_id": spec.scenario_id,
        "narrative_state": spec.narrative_state,
        "level_nature": spec.level_nature,
        "side": spec.side,
        "canon": spec.canon,
        "expected_ctx_keys": spec.expected_ctx_keys,
        "verdict": verdict,
        "reason": reason,
        "ctx_hits": ctx_hits,
        "baseline_hits": baseline_hits,
        "matches": matches,
    }


def main() -> int:
    print("=" * 78)
    print("AUDIT EMPIRIQUE — DirectionResolver scenarios S01-S10 vs LEVEL_PROB_V4")
    print("=" * 78)

    rows_nq = parse_level_prob_v4(DOC_NQ, "NQ")
    rows_es = parse_level_prob_v4(DOC_ES, "ES")
    print(f"\nParse NQ : {len(rows_nq)} levels")
    print(f"Parse ES : {len(rows_es)} levels")
    if not rows_nq or not rows_es:
        print("ERR : aucune ligne parsee. Verifier format markdown.")
        return 1

    print(f"\nScenarios audites : {len(SCENARIOS)}")
    print(f"Seuils : PF_VALIDATED={PF_VALIDATED}, PF_MARGINAL={PF_MARGINAL}, "
          f"PF_CONTEXT_BOOST={PF_CONTEXT_BOOST}, N_MIN={N_MIN}")

    results: list[dict] = []
    for spec in SCENARIOS:
        res = audit_scenario(spec, rows_es, rows_nq)
        results.append(res)

    print("\n" + "=" * 78)
    print("VERDICTS")
    print("=" * 78)
    for r in results:
        v = r["verdict"]
        marker = {
            "VALIDATED_STRONG": "[++]",
            "VALIDATED": "[OK]",
            "VALIDATED_WEAK": "[~+]",
            "MARGINAL_CTX": "[~~]",
            "NO_EMPIRICAL_CTX": "[??]",
            "NO_EMPIRICAL_DIM": "[!!]",
            "NO_EDGE": "[--]",
        }.get(v, "[??]")
        print(f"{marker} {r['scenario_id']:<42} : {v:<20} {r['reason']}")
        ctx_hits = r.get("ctx_hits", [])
        if ctx_hits:
            for m in ctx_hits[:3]:
                ctx_lbl = m.get("best_ctx_label") or m.get("best_rej_ctx") or "-"
                ctx_pf = m.get("best_ctx_pf") or m.get("best_rej_pf") or 0.0
                ctx_n = m.get("best_ctx_n")
                src = m.get("best_ctx_source", "")
                n_str = f" n_ctx={ctx_n}" if ctx_n is not None else ""
                src_str = f" [{src}]" if src else ""
                print(f"     CTX  {m['symbol']:<3} {m['level']:<18} n={m['n']:>6} "
                      f"base_pf={m['pf_baseline']:.2f}  ctx={ctx_lbl} "
                      f"ctx_pf={ctx_pf:.2f}{n_str}{src_str}")
        else:
            for m in r.get("baseline_hits", [])[:2]:
                print(f"     base {m['symbol']:<3} {m['level']:<18} n={m['n']:>6} "
                      f"pf={m['pf_baseline']:.2f} (info, ne valide PAS)")

    verdict_types = (
        "VALIDATED_STRONG", "VALIDATED", "VALIDATED_WEAK",
        "MARGINAL_CTX", "NO_EMPIRICAL_CTX", "NO_EMPIRICAL_DIM", "NO_EDGE",
    )
    summary = {"total": len(results)}
    for v in verdict_types:
        summary[v] = sum(1 for r in results if r["verdict"] == v)
    print("\n" + "=" * 78)
    print("SUMMARY")
    print("=" * 78)
    for k, v in summary.items():
        print(f"  {k}: {v}")

    # Persist
    OUT_JSON.write_text(
        json.dumps({"summary": summary, "results": results}, indent=2, default=str),
        encoding="utf-8",
    )
    print(f"\nJSON ecrit : {OUT_JSON.relative_to(ROOT)}")

    # Markdown report
    _write_markdown_report(results, summary, len(rows_nq), len(rows_es))
    print(f"MD ecrit   : {OUT_MD.relative_to(ROOT)}")

    return 0


def _write_markdown_report(results: list[dict], summary: dict, n_nq: int, n_es: int) -> None:
    lines: list[str] = []
    lines.append("# AUDIT SCENARIOS DirectionResolver vs LEVEL_PROB_V4")
    lines.append("")
    lines.append(f"**Genere** : `tools/audit_scenarios_vs_level_prob_v4.py`")
    lines.append("")
    lines.append(f"**Sources empiriques** :")
    lines.append(f"- `DOCS/LEVEL_PROB_V4_NQ.md` : {n_nq} levels parses (356K bars NQ, 318j)")
    lines.append(f"- `DOCS/LEVEL_PROB_V4_ES.md` : {n_es} levels parses (357K bars ES, 318j)")
    lines.append("")
    lines.append(f"**Seuils verdict** : PF_VALIDATED >= {PF_VALIDATED}, "
                 f"PF_MARGINAL >= {PF_MARGINAL}, PF_CONTEXT_BOOST >= {PF_CONTEXT_BOOST}, "
                 f"N_MIN >= {N_MIN}.")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append("| Verdict | Count |")
    lines.append("|---|---|")
    for k in ("VALIDATED_STRONG", "VALIDATED", "VALIDATED_WEAK",
              "MARGINAL_CTX", "NO_EMPIRICAL_CTX", "NO_EMPIRICAL_DIM", "NO_EDGE"):
        lines.append(f"| {k} | {summary.get(k, 0)} |")
    lines.append(f"| TOTAL | {summary['total']} |")
    lines.append("")

    lines.append("## Detail par scenario")
    lines.append("")
    for r in results:
        lines.append(f"### {r['scenario_id']} — {r['verdict']}")
        lines.append("")
        lines.append(f"- **NarrativeState** : `{r['narrative_state']}`")
        lines.append(f"- **level_nature** : `{r['level_nature']}`")
        lines.append(f"- **side** : `{r['side']}`")
        lines.append(f"- **Canon** : {r['canon']}")
        if r["expected_ctx_keys"]:
            lines.append(f"- **Expected ctx (LEVEL_PROB best_rej_ctx)** : "
                         f"{', '.join(f'`{k}`' for k in r['expected_ctx_keys'])}")
        lines.append(f"- **Reason** : {r['reason']}")
        lines.append("")
        if r["matches"]:
            lines.append("| Sym | Level | n | rej% | PF baseline | best_rej_ctx | best_rej_pf | match |")
            lines.append("|---|---|---|---|---|---|---|---|")
            for m in r["matches"]:
                ctx = m["best_rej_ctx"] or "-"
                bpf = f"{m['best_rej_pf']:.2f}" if m["best_rej_pf"] else "-"
                match = "BASE" if m["baseline_ok"] else ""
                if m["ctx_ok"]:
                    match = (match + "+CTX").lstrip("+")
                lines.append(
                    f"| {m['symbol']} | {m['level']} | {m['n']} | "
                    f"{m['rej_pct']:.1f}% | {m['pf_baseline']:.2f} | "
                    f"`{ctx}` | {bpf} | {match} |"
                )
            lines.append("")
        else:
            lines.append("Aucun match empirique.")
            lines.append("")

    lines.append("## Interpretation (mode STRICT)")
    lines.append("")
    lines.append("- **VALIDATED_STRONG** : >=1 level avec context match ET context_pf >= 4.0 (edge selectif fort).")
    lines.append("- **VALIDATED** : >=1 level avec context match ET context_pf >= 2.0 (edge selectif robuste).")
    lines.append("- **VALIDATED_WEAK** : >=1 level avec context match ET context_pf >= 1.3 (edge selectif marginal).")
    lines.append("- **MARGINAL_CTX** : context match mais context_pf in [1.10, 1.30) (douteux).")
    lines.append("- **NO_EMPIRICAL_CTX** : aucun level avec best_rej_ctx matchant le scenario. La ")
    lines.append("  baseline existe mais ne valide PAS le scenario (recyclage de baseline = Pattern 11 V1).")
    lines.append("- **NO_EMPIRICAL_DIM** : scenario rare event (Wyckoff) — LEVEL_PROB_V4 ne mesure ")
    lines.append("  pas la dimension event-based. Validation requiert backtest event-detection dedie.")
    lines.append("- **NO_EDGE** : aucun level avec edge baseline ni contextuel.")
    lines.append("")
    lines.append("**Limite methodologique** : LEVEL_PROB_V4 mesure rejection 30min baseline + ")
    lines.append("best_rej_ctx, pas la sequence narrative complete (state + level_nature + ")
    lines.append("confirmation pattern). Le mode STRICT n'accepte un scenario VALIDATED que si ")
    lines.append("LEVEL_PROB_V4 fournit un best_rej_ctx qui matche la condition narrative. Sinon : ")
    lines.append("incertain (NO_EMPIRICAL_CTX ou NO_EMPIRICAL_DIM) et walk-forward DSR Lopez ")
    lines.append("Phase 5 obligatoire avant tout switch live.")
    lines.append("")

    OUT_MD.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
