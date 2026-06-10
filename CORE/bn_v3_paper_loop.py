"""bn_v3_paper_loop.py — Runner BN V3 standalone Bot 2 Sim2 (Databento).

Architecture :
  - Lit meme parquet v4 enriched que Bot 2 (DATA/datasets/v4_enriched/symbol={ES,NQ}.c.0)
  - Poll nouvelles barres toutes les 30s
  - Pour chaque nouveau bar :
      * Si pas de position : run detect() -> si LONG/SHORT_ENTRY -> place bracket OCO
      * Si position active : run detect_recharge() -> si signal -> place market order +1
  - Scale-out 50% au TP_partial (move SL to BE)
  - SL hit / time stop 90min / EOD 16:00 ET -> flatten

Kill switches ENV :
  MIA_BN_V3_ENABLED=1            -> active le runner (defaut 0 = process exit immediat)
  MIA_BN_V3_RECHARGE_ENABLED=1   -> active recharges (defaut 1 par directive Jackson 07/05)
  MIA_BN_V3_DRY_RUN=1            -> log only, pas d'envoi DTC (defaut 1 pour 1ere journee)
  MIA_BN_V3_TRADE_ACCOUNT=Sim2   -> compte cible

Usage :
    set MIA_BN_V3_ENABLED=1
    set MIA_BN_V3_DRY_RUN=1
    python -X utf8 CORE/bn_v3_paper_loop.py --sym NQ

Auteur : MIA Trading System
Date   : 2026-05-07
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from CORE.bn_v3_engine import (
    BNV3Engine, BNV3State, BNV3Result,
    N_CONTRACTS_INITIAL, MAX_PYRAMID_LOADS, SCALE_OUT_TRIGGER_TICKS,
    TICK_SIZE,
)

# Logging V2
try:
    from CORE.logging_v2 import get_logger
    _v2log = get_logger("bn_v3_paper_loop", process="bn_v3_paper")
except ImportError:
    _v2log = None


def _emit(code: str, **ctx):
    if _v2log is not None:
        try:
            _v2log.emit(code, **ctx)
        except Exception as e:
            print(f"[EMIT_FAIL] code={code} err={type(e).__name__}: {e}", file=sys.stderr)


# ─── Config ───────────────────────────────────────────────────────────────

POLL_INTERVAL_SEC = 30
WINDOW_BARS = 200  # fenetre de detect (pour swings sur 90 bars + warmup)
TIME_STOP_MINUTES = 90  # 90 min - valide UNIQUEMENT si parquet v4 = 1m bars
DATA_STALENESS_MAX_SEC = 600  # SKIP si derniere bar > 10 min (pipeline incremental retard)


@dataclass
class BNV3PaperConfig:
    sym: str
    enabled: bool = False
    dry_run: bool = True
    recharge_enabled: bool = True
    trade_account: str = "Sim2"
    poll_interval_sec: int = POLL_INTERVAL_SEC


def _load_latest_window(sym: str, n_bars: int = WINDOW_BARS) -> Optional[pd.DataFrame]:
    """Charge derniere fenetre du parquet v4 enriched (1 mois courant + previous)."""
    base = ROOT / "DATA" / "datasets" / "v4_enriched" / f"symbol={sym}.c.0"
    if not base.exists():
        return None
    parquets = sorted(base.glob("**/data.parquet"))
    if not parquets:
        return None
    # Concat last 2 months pour avoir warmup (90 bars window swing)
    dfs = []
    for f in parquets[-2:]:
        try:
            df = pd.read_parquet(f)
            dfs.append(df)
        except Exception as e:
            print(f"[WARN] read {f}: {e}")
    if not dfs:
        return None
    df = pd.concat(dfs, ignore_index=True).sort_values("ts_event").reset_index(drop=True)
    return df.tail(n_bars).reset_index(drop=True)


class BNV3PaperLoop:
    """Loop principal BN V3 paper trading."""

    def __init__(self, cfg: BNV3PaperConfig):
        self.cfg = cfg
        self.engine = BNV3Engine(sym=cfg.sym, use_range_filter=True)
        self.state = BNV3State()
        self.last_processed_ts: Optional[pd.Timestamp] = None
        self.entry_ts: Optional[pd.Timestamp] = None
        self.scaled_out: bool = False
        self.contracts_open: int = 0

    def _is_eod(self, ts: pd.Timestamp) -> bool:
        """B2 fix : robuste tz naive vs aware."""
        try:
            ts_pd = pd.Timestamp(ts)
            if ts_pd.tzinfo is None:
                ts_pd = ts_pd.tz_localize("UTC")
            ts_et = ts_pd.tz_convert("US/Eastern")
            return ts_et.hour >= 16
        except Exception as e:
            print(f"[BN_V3] _is_eod tz error ts={ts}: {e}", file=sys.stderr, flush=True)
            _emit("BN_V3_LOOP_ERROR", sym=self.cfg.sym, err=f"_is_eod tz: {str(e)[:200]}")
            return False  # safe default : pas EOD

    def _check_active_position(self, df: pd.DataFrame) -> bool:
        """Retourne True si position toujours ouverte, False si SL/TP/time/EOD hit."""
        if not self.state.active or self.entry_ts is None:
            return False

        last_bar = df.iloc[-1]
        last_ts = last_bar["ts_event"]
        last_low = float(last_bar["low"])
        last_high = float(last_bar["high"])

        # EOD
        if self._is_eod(last_ts):
            self._flatten("EOD_FLATTEN")
            return False

        # Time stop 90 min (B3 fix : TIME_STOP_MINUTES, valide bars 1m parquet v4)
        minutes_in_trade = (last_ts - self.entry_ts).total_seconds() / 60.0
        if minutes_in_trade >= TIME_STOP_MINUTES:
            self._flatten("TIME_STOP_90M")
            return False

        # SL hit
        sl = self.state.sl_price
        direction = self.state.direction
        if sl is not None:
            if direction == "LONG" and last_low <= sl:
                self._flatten("SL_HIT" if not self.scaled_out else "BE_HIT")
                return False
            if direction == "SHORT" and last_high >= sl:
                self._flatten("SL_HIT" if not self.scaled_out else "BE_HIT")
                return False

        # TP scale out (50%)
        tp = self.state.tp_partial_price
        if not self.scaled_out and tp is not None:
            if direction == "LONG" and last_high >= tp:
                self._scale_out_to_be(tp)
            elif direction == "SHORT" and last_low <= tp:
                self._scale_out_to_be(tp)

        return True

    def _scale_out_to_be(self, tp_price: float):
        """Scale out 50% au TP, move SL to BE."""
        n_to_close = max(1, self.contracts_open // 2)
        new_sl = self.state.entry_price
        msg = (f"[BN_V3] SCALE_OUT 50% sym={self.cfg.sym} dir={self.state.direction} "
               f"tp={tp_price} qty_close={n_to_close} new_sl_be={new_sl}")
        print(msg, flush=True)
        _emit("BN_V3_SCALE_OUT_50",
              sym=self.cfg.sym, direction=self.state.direction,
              tp_price=tp_price, qty_close=n_to_close, new_sl=new_sl,
              dry_run=self.cfg.dry_run)
        if not self.cfg.dry_run:
            raise NotImplementedError(
                "BN V3 DTC scale_out not wired - DRY_RUN=1 only (cf code-reviewer B1 07/05). "
                "Avant activation reelle : implementer market close qty=qty_close + modify SL au BE via DTC.")
        self.contracts_open -= n_to_close
        self.scaled_out = True
        self.state.sl_price = new_sl

    def _enter(self, result: BNV3Result, ts: pd.Timestamp):
        """Enter initial 2 contrats avec bracket OCO."""
        msg = (f"[BN_V3] ENTRY {result.signal} sym={self.cfg.sym} "
               f"price={result.entry_price} sl={result.sl_price} "
               f"tp={result.tp_partial_price} qty={result.n_contracts}")
        print(msg, flush=True)
        _emit("BN_V3_ENTRY",
              sym=self.cfg.sym, direction=result.direction,
              entry_price=result.entry_price, sl=result.sl_price,
              tp_partial=result.tp_partial_price,
              qty=result.n_contracts,
              dry_run=self.cfg.dry_run)
        self.entry_ts = ts
        self.contracts_open = result.n_contracts
        self.scaled_out = False
        if not self.cfg.dry_run:
            raise NotImplementedError(
                "BN V3 DTC entry not wired - DRY_RUN=1 only (cf code-reviewer B1 07/05). "
                f"Avant activation reelle : implementer bracket OCO {result.signal} qty={result.n_contracts} "
                f"via DTC vers TradeAccount={self.cfg.trade_account}.")

    def _recharge(self, result: BNV3Result, ts: pd.Timestamp):
        """Recharge 1 contrat market."""
        msg = (f"[BN_V3] RECHARGE sym={self.cfg.sym} dir={result.direction} "
               f"n_recharges={self.state.n_recharges}/{MAX_PYRAMID_LOADS}")
        print(msg, flush=True)
        _emit("BN_V3_RECHARGE",
              sym=self.cfg.sym, direction=result.direction,
              entry_price=result.entry_price,
              n_recharges=self.state.n_recharges,
              max_recharges=MAX_PYRAMID_LOADS,
              dry_run=self.cfg.dry_run)
        self.contracts_open += 1
        if not self.cfg.dry_run:
            raise NotImplementedError(
                "BN V3 DTC recharge not wired - DRY_RUN=1 only (cf code-reviewer B1 07/05). "
                f"Avant activation reelle : envoyer market order qty=1 sym={self.cfg.sym} "
                f"dir={result.direction} TradeAccount={self.cfg.trade_account}.")

    def _flatten(self, reason: str):
        """Flatten position via Type 209."""
        msg = f"[BN_V3] FLATTEN sym={self.cfg.sym} reason={reason}"
        print(msg, flush=True)
        _emit("BN_V3_FLATTEN",
              sym=self.cfg.sym, reason=reason,
              direction=self.state.direction,
              dry_run=self.cfg.dry_run)
        if not self.cfg.dry_run:
            raise NotImplementedError(
                "BN V3 DTC flatten not wired - DRY_RUN=1 only (cf code-reviewer B1 07/05). "
                f"Avant activation reelle : Type 209 SUBMIT_FLATTEN_POSITION_ORDER sym={self.cfg.sym} "
                f"TradeAccount={self.cfg.trade_account} avec ClientOrderID obligatoire.")
        self.state = BNV3State()
        self.entry_ts = None
        self.scaled_out = False
        self.contracts_open = 0

    def step(self):
        """1 iteration : load data + detect + simulate."""
        df = _load_latest_window(self.cfg.sym, n_bars=WINDOW_BARS)
        if df is None or len(df) < 100:
            print(f"[BN_V3] sym={self.cfg.sym} insufficient data, skip", flush=True)
            return

        last_ts = df.iloc[-1]["ts_event"]

        # R4 fix : check data staleness (pipeline incremental retard)
        try:
            now_utc = pd.Timestamp.now(tz="UTC")
            ts_pd = pd.Timestamp(last_ts)
            if ts_pd.tzinfo is None:
                ts_pd = ts_pd.tz_localize("UTC")
            staleness_sec = (now_utc - ts_pd).total_seconds()
            if staleness_sec > DATA_STALENESS_MAX_SEC:
                print(f"[BN_V3] sym={self.cfg.sym} data stale {staleness_sec:.0f}s "
                      f"(>= {DATA_STALENESS_MAX_SEC}s), skip", flush=True)
                _emit("BN_V3_LOOP_ERROR", sym=self.cfg.sym,
                      err=f"data_stale staleness_sec={staleness_sec:.0f}")
                return
        except Exception as e:
            print(f"[BN_V3] staleness check fail: {e}", file=sys.stderr, flush=True)

        if self.last_processed_ts is not None and last_ts <= self.last_processed_ts:
            return  # pas de nouvelle barre
        self.last_processed_ts = last_ts

        # Si position active : check exit + recharge
        if self.state.active:
            still_active = self._check_active_position(df)
            if still_active and self.cfg.recharge_enabled:
                rec_result = self.engine.detect_recharge(df, self.state)
                if rec_result.signal in ("RECHARGE_LONG", "RECHARGE_SHORT"):
                    if self.contracts_open < N_CONTRACTS_INITIAL + MAX_PYRAMID_LOADS:
                        self._recharge(rec_result, last_ts)
        else:
            # Detect new setup
            result = self.engine.detect(df, self.state)
            if result.signal in ("LONG_ENTRY", "SHORT_ENTRY"):
                self._enter(result, last_ts)
            else:
                # Log diagnostic toutes les 5 min
                if int(time.time()) % 300 < self.cfg.poll_interval_sec:
                    print(f"[BN_V3] sym={self.cfg.sym} no_setup reason={result.reject_reason}", flush=True)

    def run(self):
        print(f"[BN_V3] Starting loop sym={self.cfg.sym} dry_run={self.cfg.dry_run} "
              f"recharge={self.cfg.recharge_enabled} account={self.cfg.trade_account}", flush=True)
        _emit("BN_V3_LOOP_START",
              sym=self.cfg.sym, dry_run=self.cfg.dry_run,
              recharge_enabled=self.cfg.recharge_enabled,
              trade_account=self.cfg.trade_account)
        while True:
            try:
                self.step()
            except Exception as e:
                print(f"[BN_V3] step error sym={self.cfg.sym}: {type(e).__name__}: {e}",
                      flush=True, file=sys.stderr)
                _emit("BN_V3_LOOP_ERROR", sym=self.cfg.sym, err=str(e)[:200])
            time.sleep(self.cfg.poll_interval_sec)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sym", choices=["NQ", "ES"], required=True)
    ap.add_argument("--poll-interval", type=int, default=POLL_INTERVAL_SEC)
    args = ap.parse_args()

    enabled = os.environ.get("MIA_BN_V3_ENABLED", "0") == "1"
    if not enabled:
        print("[BN_V3] MIA_BN_V3_ENABLED != 1 -> exit (kill switch)")
        sys.exit(0)

    dry_run = os.environ.get("MIA_BN_V3_DRY_RUN", "1") == "1"
    recharge_enabled = os.environ.get("MIA_BN_V3_RECHARGE_ENABLED", "1") == "1"
    trade_account = os.environ.get("MIA_BN_V3_TRADE_ACCOUNT", "Sim2")

    # R5 fix : valider trade_account anti default Sim3 piege Bot 1/3
    ALLOWED_ACCOUNTS = {"Sim1", "Sim2"}
    if trade_account not in ALLOWED_ACCOUNTS:
        print(f"[BN_V3] FATAL: MIA_BN_V3_TRADE_ACCOUNT='{trade_account}' "
              f"non autorise (allowed: {ALLOWED_ACCOUNTS}). Anti-piege Sim3 default.",
              file=sys.stderr)
        _emit("BN_V3_LOOP_ERROR", sym=args.sym,
              err=f"invalid trade_account: {trade_account} not in {ALLOWED_ACCOUNTS}")
        sys.exit(2)

    cfg = BNV3PaperConfig(
        sym=args.sym,
        enabled=enabled,
        dry_run=dry_run,
        recharge_enabled=recharge_enabled,
        trade_account=trade_account,
        poll_interval_sec=args.poll_interval,
    )
    loop = BNV3PaperLoop(cfg)
    loop.run()


if __name__ == "__main__":
    main()
