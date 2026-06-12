"""sierra_ts.py - Normalisation timestamp Sierra Chart LIVE pipeline.

Phase 1.5 LIVE jitter fix (12/06/2026).

# PROBLEME

Sierra Chart natif emet bars 1-min avec jitter +/-1s :
  - Bar nominale HH:MM peut fermer a HH:MM:00.000 ou HH:MM:59.000
  - Empiriquement (audit 12/06 NQ live) : 31% bars a `:59`, 69% a `:00`

Sans normalisation :
  - Cross-instrument joins ES/NQ par ts ratent (jitter different ES vs NQ)
  - Dedup naif par ts ms cree faux doublons / faux trous
  - Visualisation timestamps non-aligne sur grille minute

Fix POST-PROCESS existant (`CORE/research/sierra_dedup.py:round_ts_to_minute`)
fix le jitter en batch dedup (+45% bars recuperes verifie empirique 11/06).
**Mais le pipeline LIVE n'avait aucun fix** : bars emises avec ts brut Sierra.

Cf INCIDENT_LOG.md entry #48 (12/06 03:00).

# SOLUTION

Module dedie `CORE/sierra_ts.py` (consolidation DRY) avec :
  - `round_ts_to_minute(ts_ms)` : ROUND nearest minute (banker's rounding)
  - `normalize_payload_ts(payload)` : normalise 3 champs ts coherents +
    preserve ts_raw_ms brut pour debugging

# CONTRAT DONNEES POST-NORMALISATION

| Champ          | Convention                                        |
|----------------|---------------------------------------------------|
| `ts` (ms)      | ROUND(raw_ts_ms) = nominal minute (% 60000 == 0)  |
| `ts_event`     | ISO 8601 UTC depuis ts arrondi (coherent ts ms)   |
| `ts_event_ns`  | ts arrondi * 1_000_000 (coherent ts ms)           |
| `ts_raw_ms`    | brut Sierra preserve (debugging + tracabilite)    |

# IDEMPOTENCE

`normalize_payload_ts(normalize_payload_ts(p)) == normalize_payload_ts(p)`

Implementation : `if "ts_raw_ms" not in payload` avant set (preserve original brut).

# CONSUMERS DOWNSTREAM (audit 12/06 cross-codebase)

  - `CORE/live_enriched_reader.py:227` : dedup par `ts_event_ns` (ns)
    → coherence ts_event_ns ROUND preserve dedup correct
  - `sierra_pipeline.py:1235` : extract_ts utilise ts/ts_event/ts_event_ns
    → 3 champs coherents = pas de divergence

# REUTILISATION VS DUPLICATION

`CORE/research/sierra_dedup.py` continue d'utiliser `round_ts_to_minute`
via import depuis ce module (consolidation DRY, source unique).

Auteur : MIA Trading V2 (Phase 1.5 LIVE jitter fix)
Date   : 2026-06-12
"""
from __future__ import annotations

from datetime import datetime, timezone


def round_ts_to_minute(ts_ms: int) -> int:
    """Round ms timestamp to nearest minute (60000ms).

    Banker's rounding (Python default `round()`) sur cas 30s :
      - 08:04:30 -> 08:04:00 (even minute)
      - 08:05:30 -> 08:06:00 (odd minute)

    Edge case 30s = quasi-jamais en LIVE Sierra (distribution observee
    {`:00`, `:59`} binomiale). Acceptable.

    Args:
        ts_ms : timestamp en millisecondes epoch (Sierra brut)

    Returns:
        timestamp ms arrondi au multiple de 60000 le plus proche
    """
    return round(ts_ms / 60_000) * 60_000


def normalize_payload_ts(payload: dict) -> dict:
    """Normalize payload ts (ms), ts_event (ISO), ts_event_ns (ns) coherent.

    Preserve raw ts dans payload['ts_raw_ms']. Idempotent.

    Args:
        payload : dict mutable a normaliser (modifie in-place ET return)

    Returns:
        payload modifie (meme reference)

    Comportement :
      - Si "ts" absent ou non-numerique : NO-OP (return payload tel quel)
      - Si "ts_raw_ms" deja present : preserve (idempotence)
      - Si "ts" present : ROUND + reconstitue ts_event ISO + ts_event_ns
    """
    if "ts" not in payload:
        return payload
    ts_val = payload["ts"]
    if not isinstance(ts_val, (int, float)):
        return payload

    raw_ts_ms = int(ts_val)

    # Idempotence : preserve ORIGINAL brut si pas deja set
    # Re-normalize sur payload deja normalise = ts_raw_ms conserve la 1ere version brute
    if "ts_raw_ms" not in payload:
        payload["ts_raw_ms"] = raw_ts_ms

    ts_round_ms = round_ts_to_minute(raw_ts_ms)
    payload["ts"] = ts_round_ms

    # Coherence 3 champs ts depuis ts arrondi
    # Convention : ts_event = ISO 8601 UTC, ts_event_ns = ns epoch
    payload["ts_event"] = datetime.fromtimestamp(
        ts_round_ms / 1000.0, tz=timezone.utc
    ).isoformat()
    payload["ts_event_ns"] = ts_round_ms * 1_000_000

    return payload
