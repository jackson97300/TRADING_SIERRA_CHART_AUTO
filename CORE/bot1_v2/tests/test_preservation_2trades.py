"""Test PRESERVATION (critique) - les 2 vrais trades Bot 2 restent tradables.

Refonte Phase 4 : la nouvelle logique (verdict souple + bonus k-of-n) NE DOIT PAS
casser les 2 trades reels valides historiquement.

Donnees source : TMP_BOT2_AUTOPSY/ (copiees dans le worktree). Si absentes,
le test est skip (documente) plutot que de produire un faux echec.

  - 16/06 ES bar_ts=1781629320000 (20260616_ES_sierra_enriched.jsonl) -> SHORT
  - 17/06 ES bar_ts=1781715600000 (20260617_ES_sierra_enriched.jsonl) -> SHORT
"""
from __future__ import annotations

import json
import os

import pytest

from CORE.bot1_v2.cluster import ClusterEngine

_HERE = os.path.dirname(os.path.abspath(__file__))
# Worktree root = .../CORE/bot1_v2/tests -> remonte 3 niveaux.
_ROOT = os.path.abspath(os.path.join(_HERE, "..", "..", ".."))
_AUTOPSY_DIR = os.path.join(_ROOT, "TMP_BOT2_AUTOPSY")

_CASES = [
    ("20260616_ES_sierra_enriched.jsonl", 1781629320000),
    ("20260617_ES_sierra_enriched.jsonl", 1781715600000),
]


def _load_bar(filename: str, bar_ts: int) -> dict | None:
    path = os.path.join(_AUTOPSY_DIR, filename)
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            if (d.get("ts") or d.get("bar_ts")) == bar_ts:
                return d
    return None


@pytest.mark.parametrize("filename,bar_ts", _CASES)
def test_real_trade_stays_tradable_short(filename, bar_ts):
    """Le trade reel doit rester tradable=True + direction=SHORT."""
    bar = _load_bar(filename, bar_ts)
    if bar is None:
        pytest.skip(
            f"Donnees preservation absentes du worktree "
            f"({_AUTOPSY_DIR}/{filename}). Test skip (documente)."
        )
    engine = ClusterEngine(symbol="ES")
    decision = engine.evaluate(bar)
    assert decision.tradable is True, (
        f"PRESERVATION CASSEE {filename}: skip={decision.skip_reason} "
        f"bonus={decision.stars_count}/{decision.stars_total}"
    )
    assert decision.direction == "SHORT", (
        f"PRESERVATION {filename}: direction={decision.direction} (attendu SHORT)"
    )
