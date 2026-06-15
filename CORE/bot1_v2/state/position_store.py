"""Position store Bot 1 v2 - persistance JSON.

Pattern : 1 fichier par bot (PAS collision avec bot1 legacy).
Path : DATA/PAPER_TRADES/bot1_v2_runtime_positions.json

Format :
{
    "positions": {
        "ES": {
            "signal_id": "abc123",
            "direction": "LONG",
            "entry_price": 7600.0,
            "entry_ts": 1781234567890,
            "sl_price": 7596.5,
            "tp_price": 7606.5,
            "n_micros": 1,
            "parent_cid": "BOT1V2_P_xxx",
            "tp_cid": "BOT1V2_TP_xxx",
            "sl_cid": "BOT1V2_SL_xxx"
        }
    },
    "traded_signal_ids": ["abc123", ...],
    "cooldown_until_ts": {"ES": 1781234567, "NQ": 0},
    "last_save_ts": 1781234567
}
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Optional


class PositionStore:
    """JSON-based position store. Thread-safe via atomic rename."""

    def __init__(self, path: Optional[Path] = None):
        if path is None:
            root = Path(__file__).resolve().parents[3]
            path = root / "DATA" / "PAPER_TRADES" / "bot1_v2_runtime_positions.json"
        self.path = Path(path)
        self.positions: dict = {}  # symbol -> position dict
        self.traded_signal_ids: set = set()
        self.cooldown_until_ts: dict = {}  # symbol -> epoch seconds
        self.last_save_ts: float = 0.0

    def load(self) -> bool:
        """Charge l'etat depuis disque.

        Returns True si fichier existe et load OK.
        """
        if not self.path.exists():
            return False
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            return False
        self.positions = data.get("positions", {})
        self.traded_signal_ids = set(data.get("traded_signal_ids", []))
        self.cooldown_until_ts = data.get("cooldown_until_ts", {})
        self.last_save_ts = float(data.get("last_save_ts", 0.0))
        return True

    def save(self) -> bool:
        """Sauvegarde atomique (write tmp + rename)."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        data = {
            "positions": self.positions,
            "traded_signal_ids": list(self.traded_signal_ids),
            "cooldown_until_ts": self.cooldown_until_ts,
            "last_save_ts": time.time(),
        }
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            os.replace(tmp, self.path)
            self.last_save_ts = data["last_save_ts"]
            return True
        except OSError:
            return False

    def has_position(self, symbol: str) -> bool:
        return symbol.upper() in self.positions

    def open_position(self, symbol: str, position_data: dict) -> None:
        self.positions[symbol.upper()] = position_data
        sid = position_data.get("signal_id")
        if sid:
            self.traded_signal_ids.add(sid)

    def close_position(self, symbol: str) -> Optional[dict]:
        return self.positions.pop(symbol.upper(), None)

    def get_position(self, symbol: str) -> Optional[dict]:
        return self.positions.get(symbol.upper())

    def set_cooldown(self, symbol: str, until_ts: float) -> None:
        self.cooldown_until_ts[symbol.upper()] = until_ts

    def get_cooldown(self, symbol: str) -> float:
        return float(self.cooldown_until_ts.get(symbol.upper(), 0.0))
