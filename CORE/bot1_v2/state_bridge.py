"""State bridge Bot 1 v2 -> dashboard state.json.

Le dashboard Bot 1 PAPER (`/api/paper_trades`) lit
`DATA/PAPER_TRADES/state.json` ecrit historiquement par mia_paper_trader.py
(legacy stopped/disabled 15/06). Sans bridge, le dashboard reste fige sur
le dernier trade legacy et affiche "Trader DOWN".

Ce module maintient ce JSON pour que Bot 1 v2 soit visible au dashboard :
  - heartbeat()         : updated_ts + updated_iso (Trader UP visible)
  - rotate_day(date)    : archive closed_today + reset (00:00 UTC)
  - open_position(sym)  : ajoute a open_by_symbol
  - close_position(sym, exit_data) : add a closed_today + remove de open

Format trade compatible mia_paper_trader (schema_version=trade_v2_ml_2026_04_22).

TIER 1 (16/06/2026) : heartbeat + open + rotation. Close tracking arrive
quand on aura un listener ORDER_UPDATE DTC dans Bot 1 v2 (Tier 2).
"""
from __future__ import annotations

import json
import os
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


def _default_state_path() -> Path:
    """Chemin VPS : DATA/PAPER_TRADES/state.json (relatif au cwd nssm)."""
    root = Path(os.environ.get("MIA_ROOT", Path.cwd()))
    return root / "DATA" / "PAPER_TRADES" / "state.json"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _today_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d")


class StateBridge:
    """Maintient DATA/PAPER_TRADES/state.json compatible mia_paper_trader."""

    def __init__(self, path: Optional[Path] = None):
        self.path = path or _default_state_path()
        self.state: dict = {
            "updated_ts": time.time(),
            "updated_iso": _now_iso(),
            "date": _today_str(),
            "open_by_symbol": {},
            "closed_today": [],
        }
        # Charge le state existant (pour preserver closed_today si rotation pas faite)
        self._load_existing()

    def _load_existing(self) -> None:
        """Charge le state.json existant si compatible (meme date)."""
        try:
            if self.path.exists():
                with self.path.open("r", encoding="utf-8") as fh:
                    existing = json.load(fh)
                if isinstance(existing, dict) and existing.get("date") == _today_str():
                    self.state["closed_today"] = existing.get("closed_today", [])
                    self.state["open_by_symbol"] = existing.get("open_by_symbol", {})
        except (OSError, json.JSONDecodeError):
            # Fichier corrompu ou inaccessible : on continue avec state vide.
            # Bot 1 v2 ne doit JAMAIS crasher sur fail d'IO bridge.
            pass

    def _save(self) -> bool:
        """Atomic write : tmp + rename (pas de state.json corrompu si crash)."""
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp_fd, tmp_path = tempfile.mkstemp(
                suffix=".tmp", prefix="state_", dir=str(self.path.parent),
            )
            try:
                with os.fdopen(tmp_fd, "w", encoding="utf-8") as fh:
                    json.dump(self.state, fh, indent=2)
                os.replace(tmp_path, self.path)
                return True
            except Exception:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                return False
        except OSError:
            return False

    def heartbeat(self) -> bool:
        """Update updated_ts + updated_iso pour "Trader UP" dashboard."""
        self.state["updated_ts"] = time.time()
        self.state["updated_iso"] = _now_iso()
        return self._save()

    def rotate_day(self, new_date: str) -> bool:
        """Reset closed_today + date au passage de jour UTC.

        Archive l'ancien closed_today via un append a un historique mensuel.
        """
        old_date = self.state.get("date", "?")
        old_closed = self.state.get("closed_today", [])
        # Archive simple : append a historique mensuel
        if old_closed:
            month_archive = self.path.parent / f"closed_{old_date[:6]}.jsonl"
            try:
                with month_archive.open("a", encoding="utf-8") as fh:
                    for t in old_closed:
                        fh.write(json.dumps(t, ensure_ascii=False) + "\n")
            except OSError:
                pass  # Archive best-effort, ne bloque pas la rotation
        self.state["date"] = new_date
        self.state["closed_today"] = []
        self.state["updated_ts"] = time.time()
        self.state["updated_iso"] = _now_iso()
        return self._save()

    def open_position(self, symbol: str, *, direction: str, entry_price: float,
                       sl_price: float, tp_price: float, sl_ticks: int,
                       tp_ticks: int, signal_id: str = "",
                       sl_wall: str = "", n_micros: int = 1) -> bool:
        """Ajoute une position ouverte au state pour visibility dashboard."""
        now = time.time()
        # trade_id incremental par jour (count closed + open)
        trade_count = len(self.state["closed_today"]) + len(
            self.state.get("open_by_symbol", {})
        ) + 1
        pos = {
            "schema_version": "trade_v2_ml_2026_04_22",
            "trade_id": f"{self.state['date']}_{trade_count}",
            "signal_id": signal_id,
            "symbol": symbol,
            "direction": direction,
            "entry_price": entry_price,
            "entry_time": _now_iso(),
            "entry_ts": now,
            "sl_price": sl_price,
            "tp_price": tp_price,
            "sl_ticks": sl_ticks,
            "tp_ticks": tp_ticks,
            "sl_wall": sl_wall,
            "n_micros": n_micros,
            "current_price": entry_price,
            "unrealized_pnl_ticks": 0.0,
            "unrealized_pnl_usd": 0.0,
            "mae": 0,
            "mfe": 0,
            "bars_held": 0,
        }
        self.state["open_by_symbol"][symbol] = pos
        self.state["updated_ts"] = now
        self.state["updated_iso"] = _now_iso()
        return self._save()

    def close_position(self, symbol: str, *, exit_price: float,
                        exit_reason: str = "EXIT", outcome: str = "EXIT",
                        pnl_ticks: float = 0.0, pnl_usd: float = 0.0) -> bool:
        """Ferme la position : enleve open_by_symbol + ajoute closed_today.

        Tier 1 : appele manuellement quand Bot 1 v2 saura close (Tier 2 listener
        DTC). Pour l'instant, le bot peut appeler ca via une commande externe ou
        un listener ORDER_UPDATE futur.
        """
        pos = self.state.get("open_by_symbol", {}).pop(symbol, None)
        if pos is None:
            return False
        now = time.time()
        closed = dict(pos)
        closed.update({
            "schema_version": "trade_v2_ml_2026_04_22",
            "exit_price": exit_price,
            "exit_time": _now_iso(),
            "exit_ts": now,
            "outcome": outcome,
            "exit_reason": exit_reason,
            "pnl_ticks": pnl_ticks,
            "pnl_usd": pnl_usd,
            "duration_sec": now - closed.get("entry_ts", now),
        })
        self.state["closed_today"].append(closed)
        self.state["updated_ts"] = now
        self.state["updated_iso"] = _now_iso()
        return self._save()
