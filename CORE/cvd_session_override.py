"""cvd_session_override.py - Override Python cvd_day cassé en mode sierra.

# Contexte

INCIDENT_LOG #59 (15/06/2026) : `cvd_day` lu depuis `fpbs_cvd_day` (DMP_Reader.h:831)
qui scanne subgraph 18 de l'etude FPBS. Or sg18 = "Cumulative Sum Of Ask Volume
Bid Volume Difference - **ALL**" = cumul depuis chargement du chart, PAS reset
session. Resultat empirique 4 jours NQ : `cvd_day_dir` = CONSTANT +1 (100% bars)
-> bias_calculator.py:380 ajoute systematiquement PTS_CVD=0.25 a score_bull
-> bias bull NQ permanent + flag delta_cvd_divergence pollue.

# Solution

Recalcul cvd_day depuis `delta_bar` (= sg0 DELTA, par-bar, correct), cumule
depuis ouverture session CME (18:00 ET = boundary continuous futures).

Override `payload["cvd_day"]` et `payload["cvd_day_dir"]` en mode sierra.
Consumers downstream (bias_calculator, regime_engine, scenario_generator,
narrative_engine) voient automatiquement la version corrigee.

# State

State persistant par symbole :
  - session_id : ET-based "YYYY-MM-DD" trading session (CME 18:00 ET cutover)
  - cvd_cumul : float, cumul delta_bar depuis open session
  - n_bars_session : int, debug counter

Stocke dans `state.engine_states["cvd_session_override_{symbol}"]`.
Pickle-safe (dataclass simple).

# Hook

Apres merge `_sierra_bar` dans payload (enricher_chain.py:142) :

    from CORE.cvd_session_override import override_cvd_day_session

    if is_sierra_mode and _sierra_bar:
        # ... merge sierra ...
        override_cvd_day_session(payload, state, symbol)  # <-- ICI

# Tests

Voir `tests/sierra_port/test_cvd_session_override.py` :
  - Reset session 18:00 ET (boundary CME)
  - Cumul correct delta_bar
  - Sign +1/-1/0 distribution coherente
  - Idempotence (call 2x = meme resultat)

Date   : 2026-06-15
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Optional

try:
    from zoneinfo import ZoneInfo
    _NY_TZ = ZoneInfo("America/New_York")
except ImportError:
    # Python < 3.9 fallback (ne devrait pas arriver, VPS sur 3.11)
    _NY_TZ = None


# ════════════════════════════════════════════════════════════════════════════
# STATE
# ════════════════════════════════════════════════════════════════════════════

@dataclass
class CVDSessionOverrideState:
    """State persistant par symbole pour cumul cvd_day session-ET-based."""
    session_id: Optional[str] = None  # "YYYY-MM-DD" trading session ET
    cvd_cumul: float = 0.0
    n_bars_session: int = 0


# ════════════════════════════════════════════════════════════════════════════
# HELPERS
# ════════════════════════════════════════════════════════════════════════════

def _cme_session_id_from_ts_ms(ts_ms: int) -> str:
    """Compute CME trading session ID (ET-based, 18:00 ET boundary).

    Convention futures : trading day J commence 18:00 ET J-1, finit 17:00 ET J.
    Examples :
        ts = 2026-06-15 17:30 ET (= 21:30 UTC DST) -> session "2026-06-15"
        ts = 2026-06-15 18:30 ET (= 22:30 UTC DST) -> session "2026-06-16"
        ts = 2026-06-16 09:30 ET (= 13:30 UTC DST) -> session "2026-06-16"

    DST USA : 2nd Sunday March -> 1st Sunday November = UTC-4
    Standard (winter)         : 1st Sunday November -> 2nd Sunday March = UTC-5

    Fix code-reviewer R1 (15/06) : utiliser `zoneinfo.ZoneInfo("America/New_York")`
    pour DST automatique (vs hardcode UTC-4 qui drift novembre-mars 5 mois/an).
    Convergence avec pipeline batch `build_dataset_v4_dmp_databento.py:698` qui
    utilise deja ZoneInfo America/Chicago (CME globex 17:00 CT = 18:00 ET).
    """
    dt_utc = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
    if _NY_TZ is not None:
        dt_et = dt_utc.astimezone(_NY_TZ)
    else:
        # Fallback approximatif si zoneinfo indisponible (Python < 3.9)
        dt_et = dt_utc + timedelta(hours=-4)
    # Si heure ET >= 18, on est dans la session J+1
    if dt_et.hour >= 18:
        dt_et = dt_et + timedelta(days=1)
    return dt_et.date().isoformat()


def _sign(x: float) -> int:
    """Sign function : -1, 0, +1."""
    if x > 0:
        return 1
    if x < 0:
        return -1
    return 0


# ════════════════════════════════════════════════════════════════════════════
# OVERRIDE
# ════════════════════════════════════════════════════════════════════════════

def override_cvd_day_session(payload: dict, state, symbol: str) -> dict:
    """Override `cvd_day` et `cvd_day_dir` avec cumul session-ET-based propre.

    Args:
        payload : dict bar enriched (contient `ts`, `delta_bar`)
        state   : LiveEnricherState avec `engine_states` dict + `get_engine_state` method
        symbol  : "NQ" / "ES" / "MGC"

    Returns:
        payload muté (cvd_day + cvd_day_dir overrides). Idempotent.
    """
    ts_ms = payload.get("ts")
    delta_bar = payload.get("delta_bar")
    if ts_ms is None or delta_bar is None:
        # Bar incomplete : ne touche pas (downstream verra ancien cvd_day casse,
        # mais c'est preferable a un crash). Log silencieux.
        return payload

    # State engine_state key per symbol (chaque instrument session independante).
    state_key = f"cvd_session_override_{symbol}"
    s = state.get_engine_state(state_key, factory=CVDSessionOverrideState)

    # Compute session_id depuis ts
    session_id = _cme_session_id_from_ts_ms(int(ts_ms))

    # Reset si nouvelle session
    if s.session_id != session_id:
        s.session_id = session_id
        s.cvd_cumul = 0.0
        s.n_bars_session = 0

    # Cumul
    try:
        s.cvd_cumul += float(delta_bar)
    except (TypeError, ValueError):
        return payload  # delta_bar invalide, skip
    s.n_bars_session += 1

    # Override fields casses (sg18 ALL bug)
    payload["cvd_day"] = s.cvd_cumul
    payload["cvd_day_dir"] = _sign(s.cvd_cumul)

    return payload
