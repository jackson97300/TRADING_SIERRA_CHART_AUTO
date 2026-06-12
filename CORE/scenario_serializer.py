"""scenario_serializer.py - Phase B.5.4 JSONL serialization.

Serialise les ScenarioInstance terminees (COMPLETED/INVALIDATED/EXPIRED) en
JSONL append-only pour Phase C calibration empirique (Platt scaling /
isotonic regression Lopez AFML ch.13).

# Schema JSONL

1 ligne = 1 ScenarioInstance terminee. Champs cles :
- scenario_id : UUID stable cross-bar (join key Phase C)
- scenario_name, symbol, side, setup_type
- created_at_ts / terminal_ts / terminal_state
- entry_price / entry_zone / target_1 / target_2 / stop_loss / atr_at_creation
- heuristic_score_at_creation / heuristic_score_current / regime_vix_at_creation
- entry_touched_at_ts / triggered_at_ts / target_1_hit_at_ts / target_2_hit_at_ts / stop_hit_at_ts
- bars_alive / bars_in_zone / bars_no_match
- mfe_atr / mae_atr / outcome_pnl_atr / outcome_pnl_r
- invalidation_reason / expiration_reason
- key_levels_used / rationale
- validation_matches (transitions matched_conditions agreges)

# Rotation

1 fichier par jour ET (convention futures, aligne avec fix DMP_OpenType #54).
Path : LOGS/scenarios/YYYY-MM-DD_scenarios_{symbol}.jsonl

# Fail-safe

Toute erreur d'ecriture emit SCENARIO_JSONL_WRITE_FAIL (MAJEUR) mais
n'interrompt pas le tracker (anti-cascade).

Auteur : MIA Trading V5 Phase B.5.4 Serializer
Date   : 2026-06-12
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

# Fix review #4 (12/06) : zoneinfo precision DST exacte (stdlib Python 3.9+)
# au lieu de l'approximation `3 <= mo <= 10` (faux 2-3j autour DST shifts).
try:
    from zoneinfo import ZoneInfo
    _TZ_ET = ZoneInfo("America/New_York")
except ImportError:
    _TZ_ET = None  # fallback approximation pour Python < 3.9


# ════════════════════════════════════════════════════════════════════════════
# CONFIG
# ════════════════════════════════════════════════════════════════════════════

DEFAULT_LOGS_DIR = "LOGS/scenarios"


# ════════════════════════════════════════════════════════════════════════════
# SESSION DATE ET (aligne avec fix DMP_OpenType #54)
# ════════════════════════════════════════════════════════════════════════════

def session_date_id_from_ts(ts_ms: int) -> str:
    """Retourne YYYY-MM-DD du trading day ET pour un ts_ms epoch UTC.

    Convention futures (aligne DMP_OT_GetSessionDateID C++) :
    - bars 00:00-17:59 ET du jour D -> session D
    - bars 18:00-23:59 ET du jour D -> session D+1

    Fix review #4 (12/06) : utilise zoneinfo.ZoneInfo("America/New_York") si
    disponible (precision DST exacte). Fallback approximation si Python <3.9.
    """
    if ts_ms <= 0:
        return "0000-00-00"
    dt_utc = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
    if _TZ_ET is not None:
        # Conversion ET exacte via zoneinfo (gere DST automatiquement)
        dt_et = dt_utc.astimezone(_TZ_ET)
    else:
        # Fallback approximation pour Python < 3.9
        mo = dt_utc.month
        is_dst = 3 <= mo <= 10
        offset_h = 4 if is_dst else 5
        dt_et = (dt_utc - timedelta(hours=offset_h)).replace(tzinfo=None)
    if dt_et.hour >= 18:
        dt_et = dt_et + timedelta(days=1)
    return dt_et.strftime("%Y-%m-%d")


# ════════════════════════════════════════════════════════════════════════════
# SERIALIZER
# ════════════════════════════════════════════════════════════════════════════

class JSONLSerializer:
    """Append-only serializer pour ScenarioInstance terminees.

    Usage :
        serializer = JSONLSerializer(logs_dir="LOGS/scenarios", symbol="NQ")
        for inst in terminal_instances:
            serializer.write(inst)
    """

    def __init__(self, symbol: str,
                 logs_dir: str = DEFAULT_LOGS_DIR,
                 log_emit=None):
        self.symbol = symbol
        self.logs_dir = Path(logs_dir)
        self._log_emit = log_emit
        self._current_path: Optional[Path] = None
        self._current_date: Optional[str] = None
        self.logs_dir.mkdir(parents=True, exist_ok=True)

    def write(self, instance) -> bool:
        """Serialise une ScenarioInstance terminee en 1 ligne JSONL.

        Returns:
            True si ecriture OK, False si erreur (fail-safe).
        """
        try:
            payload = serialize_instance(instance)
        except Exception as exc:  # noqa: BLE001
            self._emit_fail("serialize_error", exc)
            return False
        ts_anchor = instance.terminal_ts or instance.created_at_ts
        date_id = session_date_id_from_ts(ts_anchor)
        self._rotate_if_needed(date_id)
        try:
            with open(self._current_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(payload, ensure_ascii=False) + "\n")
            return True
        except Exception as exc:  # noqa: BLE001
            self._emit_fail("write_error", exc)
            return False

    def _rotate_if_needed(self, date_id: str) -> None:
        if date_id != self._current_date:
            self._current_date = date_id
            self._current_path = self.logs_dir / f"{date_id}_scenarios_{self.symbol}.jsonl"

    def _emit_fail(self, kind: str, exc: Exception) -> None:
        if self._log_emit is None:
            return
        try:
            self._log_emit("SCENARIO_JSONL_WRITE_FAIL", {
                "path": str(self._current_path) if self._current_path else "<no_path>",
                "err": f"{kind}: {str(exc)[:200]}",
            })
        except Exception:  # noqa: BLE001
            pass


# ════════════════════════════════════════════════════════════════════════════
# SERIALIZE ScenarioInstance -> dict
# ════════════════════════════════════════════════════════════════════════════

def serialize_instance(inst) -> dict:
    """Convertit une ScenarioInstance en dict serialisable JSON.

    Note : state_history (list[StateTransition]) compact en validation_matches
    (agregation des matched_conditions). conditions_validation/invalidation
    serialisees en list[str] description pour humain (eval state runtime perdu
    mais conserve l'audit).
    """
    # Aggregation validation_matches depuis state_history
    validation_matches = []
    triggered_via_conditions = False
    for t in inst.state_history:
        if t.to_state in ("TRIGGERED", "VALIDATED"):
            validation_matches.extend(t.matched_conditions)
        # Fix review #2 (12/06) : distinguer trigger via conditions vs skip TRIGGERED
        # Phase C calibration : sample qualitativement different selon que les
        # conditions_validation ont matche ou non. target_1_hit_no_trigger = skip.
        if t.to_state == "TRIGGERED" and t.trigger == "validation_match":
            triggered_via_conditions = True
    validation_matches = list(dict.fromkeys(validation_matches))  # dedup preserve order

    transitions = [
        {
            "from": t.from_state,
            "to": t.to_state,
            "ts": t.ts_ms,
            "bar_idx": t.bar_index,
            "trigger": t.trigger,
            "bar_close": t.bar_close,
        }
        for t in inst.state_history
    ]

    return {
        "scenario_id": inst.scenario_id,
        "scenario_name": inst.scenario_name,
        "symbol": inst.symbol,
        "side": inst.side,
        "setup_type": inst.setup_type,
        # Timing
        "created_at_ts": inst.created_at_ts,
        "terminal_ts": inst.terminal_ts,
        "terminal_state": inst.state,
        "bars_alive": inst.bars_alive,
        "bars_in_zone": inst.bars_in_zone,
        # Niveaux
        "entry_price": inst.entry_price,
        "entry_zone_low": inst.entry_zone_low,
        "entry_zone_high": inst.entry_zone_high,
        "target_1": inst.target_1,
        "target_2": inst.target_2,
        "stop_loss": inst.stop_loss,
        "atr_at_creation": inst.atr_at_creation,
        # Scoring
        "heuristic_score_at_creation": inst.heuristic_score_at_creation,
        "heuristic_score_current": inst.heuristic_score_current,
        "regime_vix_at_creation": inst.regime_vix_at_creation,
        # Outcome tracking
        "entry_touched_at_ts": inst.entry_touched_at_ts,
        "triggered_at_ts": inst.triggered_at_ts,
        "target_1_hit_at_ts": inst.target_1_hit_at_ts,
        "target_2_hit_at_ts": inst.target_2_hit_at_ts,
        "stop_hit_at_ts": inst.stop_hit_at_ts,
        "mfe_atr": inst.mfe_atr,
        "mae_atr": inst.mae_atr,
        "outcome_pnl_atr": inst.outcome_pnl_atr,
        "outcome_pnl_r": inst.outcome_pnl_r,
        # Audit
        "invalidation_reason": inst.invalidation_reason,
        "expiration_reason": inst.expiration_reason,
        "validation_matches": validation_matches,
        "triggered_via_conditions": triggered_via_conditions,
        "transitions_count": len(inst.state_history),
        "transitions": transitions,
        # Narrative cross-link
        "key_levels_used": list(inst.key_levels_used),
        "rationale": inst.rationale,
    }
