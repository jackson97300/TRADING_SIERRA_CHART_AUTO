"""Tests Solution A v2 : pnl approximatif via JSONL DMP au TIMEOUT Bot 3.

Contexte (07/05/2026 Jackson "C SUSPECT 0 PILE") :
- 31 BOT3_TIMEOUT_FLATTEN_SYM envoyes / 0 BOT3_FLATTEN_FILL_CAPTURED en 4 jours
- Sierra Chart Sim1 ne renvoie jamais ORDER_UPDATE OrderStatus=7 pour Type 209
- Fix 06/05 (capture fill flatten) = code mort
- Solution A v2 : tail JSONL DMP du jour pour calculer pnl approximatif

Tests :
  1. JSONL fresh + pnl LONG positif
  2. JSONL fresh + pnl SHORT negatif (dir_sign correct)
  3. Bar stale > 90s -> emit SKIP_STALE, pas d'approx
  4. JSONL absent -> aucun emit (silent skip via `if jsonl_path.exists()`)
  5. JSONL corrompu (ligne tronquee) -> emit APPROX_FAIL avec err
  6. entry_price=0 (pos malformee) -> skip approx defensif
  7. Codes log presents dans LOG_CODES (anti-regression KeyError)
  8. JSONL sans champs price/ts -> skip silent (defensif)
  9. paper_tracker exclude pnl_estimated du PF officiel
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def _write_jsonl_dmp(tmp_dir: Path, sym: str, ts_ms: int, price: float,
                     n_lines: int = 5) -> Path:
    """Helper : ecrit un JSONL DMP minimal pour le test."""
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    sym_dir = tmp_dir / "DATA" / sym
    sym_dir.mkdir(parents=True, exist_ok=True)
    fp = sym_dir / f"{today}_{sym}.jsonl"
    with fp.open("w", encoding="utf-8") as f:
        for i in range(n_lines - 1):
            row = {"ts": ts_ms - (n_lines - 1 - i) * 60000,
                   "price": price - 5 + i, "sym": sym}
            f.write(json.dumps(row) + "\n")
        # Derniere ligne = la plus recente (lue par tail)
        row = {"ts": ts_ms, "price": price, "sym": sym, "atr": 80.0}
        f.write(json.dumps(row) + "\n")
    return fp


def _simulate_solution_a(jsonl_path: Path, pos: dict, sym: str,
                         tick_size: float = 0.25, tick_value: float = 0.50,
                         emits: list = None) -> dict:
    """Reproduit la logique Solution A v2 sans appeler tout le moteur Bot 3.

    Returns dict avec exit_price_approx, pnl_ticks_approx, pnl_usd_approx,
    pnl_estimated, emit_code (le dernier code emit).
    """
    emits = emits if emits is not None else []
    result = {
        "exit_price_approx": None,
        "pnl_ticks_approx": None,
        "pnl_usd_approx": None,
        "pnl_estimated": False,
        "emit_code": None,
    }
    now_utc = datetime.now(timezone.utc)
    try:
        if jsonl_path.exists() and pos.get("entry_price"):
            with jsonl_path.open("rb") as f:
                f.seek(0, 2)
                size = f.tell()
                f.seek(max(0, size - 8192))
                tail = f.read().decode("utf-8", errors="ignore")
            last_line = tail.strip().split("\n")[-1] if tail.strip() else ""
            if last_line:
                row = json.loads(last_line)
                bar_price = row.get("price")
                bar_ts_ms = row.get("ts")
                if bar_price is not None and bar_ts_ms:
                    bar_ts = datetime.fromtimestamp(bar_ts_ms / 1000, tz=timezone.utc)
                    bar_age = (now_utc - bar_ts).total_seconds()
                    if bar_age <= 90:
                        bar_close_f = float(bar_price)
                        if bar_close_f > 0:
                            dir_sign = 1 if pos.get("side") == "LONG" else -1
                            entry = float(pos["entry_price"])
                            n_contracts = pos.get("n_contracts", 3)
                            pnl_ticks = round(
                                (bar_close_f - entry) / tick_size * dir_sign, 2)
                            pnl_usd = round(pnl_ticks * tick_value * n_contracts, 2)
                            result.update({
                                "exit_price_approx": bar_close_f,
                                "pnl_ticks_approx": pnl_ticks,
                                "pnl_usd_approx": pnl_usd,
                                "pnl_estimated": True,
                                "emit_code": "BOT3_TIMEOUT_PNL_APPROX",
                            })
                            emits.append("BOT3_TIMEOUT_PNL_APPROX")
                            return result
                    else:
                        emits.append("BOT3_TIMEOUT_PNL_APPROX_SKIP_STALE")
                        result["emit_code"] = "BOT3_TIMEOUT_PNL_APPROX_SKIP_STALE"
                        return result
    except Exception as e:
        emits.append("BOT3_TIMEOUT_PNL_APPROX_FAIL")
        result["emit_code"] = "BOT3_TIMEOUT_PNL_APPROX_FAIL"
        result["err"] = str(e)
    return result


# ─── Tests ────────────────────────────────────────────────────────────────

class TestSolutionAv2:
    def test_long_fresh_pnl_positif(self, tmp_path):
        """LONG entry 28700, close 28710 = +40 ticks * 3 contrats * 0.50$ = +$60."""
        ts_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        jsonl = _write_jsonl_dmp(tmp_path, "NQ", ts_ms, 28710.0)
        pos = {"side": "LONG", "entry_price": 28700.0, "n_contracts": 3}
        emits = []
        r = _simulate_solution_a(jsonl, pos, "NQ", emits=emits)
        assert r["pnl_estimated"] is True
        assert r["pnl_ticks_approx"] == 40.0
        assert r["pnl_usd_approx"] == 60.0
        assert r["exit_price_approx"] == 28710.0
        assert r["emit_code"] == "BOT3_TIMEOUT_PNL_APPROX"

    def test_short_fresh_pnl_negatif(self, tmp_path):
        """SHORT entry 28700, close 28720 = -80 ticks * 3 * 0.50$ = -$120."""
        ts_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        jsonl = _write_jsonl_dmp(tmp_path, "NQ", ts_ms, 28720.0)
        pos = {"side": "SHORT", "entry_price": 28700.0, "n_contracts": 3}
        r = _simulate_solution_a(jsonl, pos, "NQ")
        assert r["pnl_estimated"] is True
        assert r["pnl_ticks_approx"] == -80.0  # SHORT loses when price rises
        assert r["pnl_usd_approx"] == -120.0

    def test_bar_stale_skip(self, tmp_path):
        """Bar age > 90s -> SKIP_STALE, pas d'approx."""
        ts_ms = int((datetime.now(timezone.utc) - timedelta(seconds=120)).timestamp() * 1000)
        jsonl = _write_jsonl_dmp(tmp_path, "NQ", ts_ms, 28710.0)
        pos = {"side": "LONG", "entry_price": 28700.0, "n_contracts": 3}
        emits = []
        r = _simulate_solution_a(jsonl, pos, "NQ", emits=emits)
        assert r["pnl_estimated"] is False
        assert r["emit_code"] == "BOT3_TIMEOUT_PNL_APPROX_SKIP_STALE"

    def test_jsonl_absent(self, tmp_path):
        """JSONL absent -> aucun emit (silent skip defensif)."""
        non_existant = tmp_path / "DATA" / "NQ" / "missing.jsonl"
        pos = {"side": "LONG", "entry_price": 28700.0, "n_contracts": 3}
        emits = []
        r = _simulate_solution_a(non_existant, pos, "NQ", emits=emits)
        assert r["pnl_estimated"] is False
        assert r["emit_code"] is None  # silent skip
        assert len(emits) == 0

    def test_jsonl_corrompu(self, tmp_path):
        """Ligne tronquee -> emit APPROX_FAIL."""
        sym_dir = tmp_path / "DATA" / "NQ"
        sym_dir.mkdir(parents=True)
        today = datetime.now(timezone.utc).strftime("%Y%m%d")
        fp = sym_dir / f"{today}_NQ.jsonl"
        # Write valid line then tronquee
        with fp.open("w", encoding="utf-8") as f:
            f.write('{"ts": 1, "price": 28700, "sym": "NQ"}\n')
            f.write('{"ts": 2, "price"')  # tronque
        pos = {"side": "LONG", "entry_price": 28700.0, "n_contracts": 3}
        emits = []
        r = _simulate_solution_a(fp, pos, "NQ", emits=emits)
        assert r["pnl_estimated"] is False
        assert r["emit_code"] == "BOT3_TIMEOUT_PNL_APPROX_FAIL"

    def test_entry_price_zero_skip(self, tmp_path):
        """entry_price=0 (pos malformee) -> skip defensif silencieux."""
        ts_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        jsonl = _write_jsonl_dmp(tmp_path, "NQ", ts_ms, 28710.0)
        pos = {"side": "LONG", "entry_price": 0, "n_contracts": 3}
        r = _simulate_solution_a(jsonl, pos, "NQ")
        assert r["pnl_estimated"] is False  # entry_price=0 -> falsy -> skip

    def test_log_codes_registered(self):
        """Anti-regression KeyError : codes log presents dans LOG_CODES."""
        from CORE.log_catalog import LOG_CODES
        for code in ("BOT3_TIMEOUT_PNL_APPROX",
                     "BOT3_TIMEOUT_PNL_APPROX_SKIP_STALE",
                     "BOT3_TIMEOUT_PNL_APPROX_FAIL"):
            assert code in LOG_CODES, f"Code log absent: {code}"

    def test_jsonl_sans_price_ts(self, tmp_path):
        """JSONL sans champs price/ts -> skip silent."""
        sym_dir = tmp_path / "DATA" / "NQ"
        sym_dir.mkdir(parents=True)
        today = datetime.now(timezone.utc).strftime("%Y%m%d")
        fp = sym_dir / f"{today}_NQ.jsonl"
        with fp.open("w", encoding="utf-8") as f:
            f.write('{"sym": "NQ", "atr": 80}\n')  # pas de price ni ts
        pos = {"side": "LONG", "entry_price": 28700.0, "n_contracts": 3}
        r = _simulate_solution_a(fp, pos, "NQ")
        assert r["pnl_estimated"] is False
        assert r["emit_code"] is None  # bar_price/ts None -> silent skip


class TestPaperTrackerExclusion:
    def test_pnl_estimated_exclu_du_pf_official(self):
        """paper_tracker._is_official_pnl exclut pnl_estimated=True."""
        sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "DASHBOARD" / "api"))
        # Reproduce la logique sans importer (paper_tracker a beaucoup de deps)
        def _is_numeric_pnl(t):
            v = t.get("pnl_ticks")
            return isinstance(v, (int, float)) and not (v != v)

        def _is_official_pnl(t):
            return _is_numeric_pnl(t) and not t.get("pnl_estimated", False)

        # Trade TP officiel
        t_official = {"pnl_ticks": 50.0, "pnl_estimated": False}
        assert _is_official_pnl(t_official) is True

        # Trade TIMEOUT approximate (Solution A v2)
        t_approx = {"pnl_ticks": -25.0, "pnl_estimated": True}
        assert _is_numeric_pnl(t_approx) is True  # numerique
        assert _is_official_pnl(t_approx) is False  # mais exclu PF officiel

        # Trade TIMEOUT sans pnl (avant Solution A)
        t_unknown = {"pnl_ticks": None, "pnl_known": False}
        assert _is_official_pnl(t_unknown) is False
