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
    "last_trade_ts_by_symbol": {"ES": "2026-06-18T08:01:16+00:00", "NQ": null},
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
        # Time-based cooldown : symbole -> ISO 8601 UTC du dernier trade.
        # Persiste cross-restart (fix bug 18/06 : restart bypass cooldown counter-based).
        self.last_trade_ts_by_symbol: dict = {}
        # Anti-clustering spatial (18/06) : (symbol, direction) -> dernier prix entry.
        # Cles : "ES_LONG" / "ES_SHORT" / "NQ_LONG" / ... persistees cross-restart.
        self.last_entry_price_by_sym_dir: dict = {}
        # Config snapshot (18/06) : permet au dashboard de lire la config active du bot
        # sans depender de ses env vars (process distincts nssm).
        # Le bot persiste {"cooldown_minutes": 15, "max_hold_minutes": 30} au boot.
        self.meta_config: dict = {}
        # Circuit breaker (anti-stubbornness 18/06) : compteur SL consecutives par
        # symbole + halt_until_ts par symbole. Persistes cross-restart pour eviter
        # bypass via crash (carnage 18/06 -$1025 sur 4 SL LONG ES sans halt).
        self.n_sl_consec_by_symbol: dict = {}  # {"ES": 3, "NQ": 0}
        self.halt_until_ts_by_symbol: dict = {}  # {"ES": 1781780000.0, "NQ": 0.0}
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
        self.last_trade_ts_by_symbol = data.get("last_trade_ts_by_symbol", {})
        self.last_entry_price_by_sym_dir = data.get("last_entry_price_by_sym_dir", {})
        self.meta_config = data.get("meta_config", {})
        self.n_sl_consec_by_symbol = data.get("n_sl_consec_by_symbol", {})
        self.halt_until_ts_by_symbol = data.get("halt_until_ts_by_symbol", {})
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
            "last_trade_ts_by_symbol": self.last_trade_ts_by_symbol,
            "last_entry_price_by_sym_dir": self.last_entry_price_by_sym_dir,
            "meta_config": self.meta_config,
            "n_sl_consec_by_symbol": self.n_sl_consec_by_symbol,
            "halt_until_ts_by_symbol": self.halt_until_ts_by_symbol,
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

    def set_last_trade_ts(self, symbol: str, iso_dt: str) -> None:
        """Enregistre l'ISO 8601 UTC du dernier trade pour cooldown time-based.

        Persiste cross-restart : le bot ne peut plus bypass le cooldown via crash.
        Cf fix bug 18/06 (Trade #3 entry @01:13 alors que Trade #2 @00:55 + restart
        intermediaire bypassait counter-based reset).
        """
        self.last_trade_ts_by_symbol[symbol.upper()] = iso_dt

    def get_last_trade_ts(self, symbol: str) -> Optional[str]:
        """Returns ISO 8601 UTC du dernier trade enregistre, ou None si jamais trade."""
        return self.last_trade_ts_by_symbol.get(symbol.upper())

    def set_last_entry_price(self, symbol: str, direction: str, price: float) -> None:
        """Memorise le dernier prix d'entry pour (symbol, direction).

        Persiste cross-restart (fix 18/06 : anti-clustering spatial).
        Pattern observe : 5 LONGs ES dans 13 ticks = -$237.50 sur entry over-tradee.
        """
        key = f"{symbol.upper()}_{direction.upper()}"
        self.last_entry_price_by_sym_dir[key] = float(price)

    def get_last_entry_price(self, symbol: str, direction: str) -> Optional[float]:
        """Retourne le dernier prix d'entry pour (symbol, direction), ou None si jamais."""
        key = f"{symbol.upper()}_{direction.upper()}"
        val = self.last_entry_price_by_sym_dir.get(key)
        if val is None:
            return None
        try:
            return float(val)
        except (TypeError, ValueError):
            return None

    def set_meta_config(self, cooldown_minutes: int, max_hold_minutes: int) -> None:
        """Persiste la config active du bot pour les consumers externes (dashboard).

        Source unique de verite : le bot ecrit, les autres process lisent.
        Evite la decorrelation env vars entre process nssm distincts.
        """
        self.meta_config = {
            "cooldown_minutes": int(cooldown_minutes),
            "max_hold_minutes": int(max_hold_minutes),
        }

    # ------------------------------------------------------------------
    # CIRCUIT BREAKER helpers (anti-stubbornness 18/06/2026)
    # ------------------------------------------------------------------
    # Carnage 18/06 : -$1025 broker E-mini sur 4 SL LONG ES d'affilee sans halt.
    # Trader pro stoppe a 3 SL pour reassesser. Reset compteur au prochain TP.
    # Persistes cross-restart pour eviter bypass via crash Python.

    def get_n_sl_consec(self, symbol: str) -> int:
        """Retourne le nombre de SL consecutives actuel pour ce symbole."""
        return int(self.n_sl_consec_by_symbol.get(symbol.upper(), 0))

    def increment_sl_consec(self, symbol: str) -> int:
        """Incremente le compteur SL consecutives, retourne la nouvelle valeur."""
        sym = symbol.upper()
        cur = int(self.n_sl_consec_by_symbol.get(sym, 0))
        cur += 1
        self.n_sl_consec_by_symbol[sym] = cur
        return cur

    def reset_sl_consec(self, symbol: str) -> None:
        """Reset compteur SL consecutives (a appeler sur TP / breakeven)."""
        self.n_sl_consec_by_symbol[symbol.upper()] = 0

    def get_halt_until_ts(self, symbol: str) -> float:
        """Retourne l'epoch ts (sec) jusqu'a laquelle le trading est halt sur ce sym.

        Retourne 0.0 si jamais halt. Le caller compare a time.time() pour decider.
        """
        return float(self.halt_until_ts_by_symbol.get(symbol.upper(), 0.0))

    def set_halt_until_ts(self, symbol: str, ts: float) -> None:
        """Set l'epoch ts (sec) jusqu'a laquelle le trading est halt sur ce sym."""
        self.halt_until_ts_by_symbol[symbol.upper()] = float(ts)
