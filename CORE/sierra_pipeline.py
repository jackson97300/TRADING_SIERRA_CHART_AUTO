"""sierra_pipeline.py — Orchestrateur Phase 4.1 Sierra Full Migration.

Phase 4.1 Sierra Full Migration (10/06/2026).
Cf design doc DOCS/superpowers/specs/2026-06-06-sierra-full-migration-design.md s4.

Chain les 9 modules Phase 3 sur les bars Sierra natif (DMP schema 3.7.22).
Output : payload enrichi Sierra (380) + Phase 3 derive (113) = ~493 cols.

Architecture :
  Sierra DMP JSONL (live ou backfill)
       |
       v
  SierraLiveReader (sierra_live_io.py existant)
       |
       v
  SierraPipelineOrchestrator (CE MODULE)
   |- POCMigrationCalculator      (2 features)
   |- SwingsV2Calculator           (6 features)
   |- PrevLevelsCalculator         (18 features)
   |- SessionsFineCalculator       (35 features)
   |- DivergencesV2Calculator      (14 features)
   |- CtxRollingCalculator         (25 features)
   |- compute_roll_features_batch  (3 features, stateless)
   |- compute_eco_news_features    (10 features, stateless)
   |- session_utils helpers        (cross-module)
       |
       v
  JSONL enrichi (Sierra + Phase 3)

Cross-day reset :
  - Detection automatique via session_utils.compute_trading_date
  - Tous les Calculator stateful sont reset au boundary 18:00 ET CME

Mode dual-run (Phase 4.2-4.3) :
  - Compare Sierra+Phase3 vs Databento+enricher_chain actuel
  - Convergence > 95% par feature SIGNED (Sharpe haircut Bonferroni)

Auteur : MIA Trading V2 (Phase 4.1 Sierra Migration)
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Optional

import numpy as np
import pandas as pd

try:
    from CORE.poc_migration import POCMigrationCalculator
    from CORE.swings_v2 import SwingsV2Calculator
    from CORE.prev_levels import PrevLevelsCalculator
    from CORE.sessions_fine import SessionsFineCalculator
    from CORE.divergences_v2 import DivergencesV2Calculator
    from CORE.ctx_rolling import CtxRollingCalculator
    from CORE.roll_calendar import compute_roll_features
    from CORE.eco_news_features import compute_eco_news_features
    from CORE.session_utils import get_trading_date_from_utc, utc_to_et
except ImportError:
    # Fallback si on lance depuis CORE/ directement
    from poc_migration import POCMigrationCalculator
    from swings_v2 import SwingsV2Calculator
    from prev_levels import PrevLevelsCalculator
    from sessions_fine import SessionsFineCalculator
    from divergences_v2 import DivergencesV2Calculator
    from ctx_rolling import CtxRollingCalculator
    from roll_calendar import compute_roll_features
    from eco_news_features import compute_eco_news_features
    from session_utils import get_trading_date_from_utc, utc_to_et


# Default tick size par symbole (fallback si manquant)
DEFAULT_TICK_SIZE_BY_SYMBOL = {
    "ES": 0.25, "NQ": 0.25, "MGC": 0.10, "GC": 0.10,
}


class SierraPipelineOrchestrator:
    """Orchestrateur des 9 modules Phase 3 sur bars Sierra natif.

    Usage:
        pipeline = SierraPipelineOrchestrator(symbol="NQ")
        for sierra_bar in stream_bars:
            enriched = pipeline.enrich_bar(sierra_bar)
            write_jsonl(enriched)

    Cross-day reset :
        Detection automatique session_date_trading boundary 18:00 ET CME.
        Tous les Calculator stateful reset au passage de jour.
        Les Calculator batch (roll_calendar, eco_news) sont stateless.

    Concurrency :
        Une instance = un symbole. Pas thread-safe (state interne mutable).
        Pour multi-symbol : creer 1 instance par symbol.
    """

    def __init__(self, symbol: str = "NQ") -> None:
        self.symbol = symbol.upper()
        self.tick_size = DEFAULT_TICK_SIZE_BY_SYMBOL.get(self.symbol, 0.25)

        # Initialize stateful calculators
        self._poc_migration = POCMigrationCalculator()
        self._swings_v2 = SwingsV2Calculator(tick_size=self.tick_size)
        self._prev_levels = PrevLevelsCalculator()
        self._sessions_fine = SessionsFineCalculator()
        self._divergences_v2 = DivergencesV2Calculator()
        self._ctx_rolling = CtxRollingCalculator()

        # Cross-day tracking
        self._current_trading_date: Optional[date] = None

        # Stats orchestrateur (debug + monitoring)
        self._bars_processed: int = 0
        self._bars_skipped_nan: int = 0
        self._cross_day_resets: int = 0

    def enrich_bar(
        self,
        sierra_bar: dict,
        bar_ts_utc: Optional[datetime] = None,
    ) -> dict:
        """Enrichit une bar Sierra natif avec les 113 features Phase 3.

        Args:
            sierra_bar : dict bar Sierra natif (380 cols schema 3.7.22).
                Champs requis : close, bar_high, bar_low, delta_bar,
                total_vol, atr, dist_swing_high, dist_swing_low,
                dist_cur_vpoc. Optionnels : vwap_d, finish_strength,
                range_pos, va_position_pct, bn_absorb_ask/bid, buy_vol, sell_vol.
            bar_ts_utc : timestamp UTC tz-aware. Si None, extrait de sierra_bar
                ["ts_event_ns"] ou ["ts_utc"].

        Returns:
            dict : sierra_bar + features Phase 3 (113 ajoutees).

        Raises:
            ValueError : si bar_ts_utc absent ET non extractible.
        """
        # Resolve timestamp
        if bar_ts_utc is None:
            bar_ts_utc = self._extract_ts_utc(sierra_bar)

        if bar_ts_utc.tzinfo is None:
            bar_ts_utc = bar_ts_utc.replace(tzinfo=timezone.utc)

        # Detection cross-day (CME 18:00 ET reset)
        trading_date = get_trading_date_from_utc(bar_ts_utc)
        if self._maybe_cross_day_reset(trading_date):
            self._cross_day_resets += 1

        # Start with Sierra natif bar
        enriched = dict(sierra_bar)
        self._bars_processed += 1

        # ─── Module 3.1 : POC Migration (2 features) ───
        poc_feats = self._poc_migration.update(
            dist_cur_vpoc=sierra_bar.get("dist_cur_vpoc"),
        )
        enriched.update(poc_feats)

        # ─── Module 3.2 : Swings V2 Wyckoff/ICT (6 features) ───
        swings_feats = self._swings_v2.update(
            dist_swing_high=sierra_bar.get("dist_swing_high"),
            dist_swing_low=sierra_bar.get("dist_swing_low"),
            bar_high=sierra_bar.get("bar_high"),
            bar_low=sierra_bar.get("bar_low"),
            close=sierra_bar.get("close"),
        )
        enriched.update(swings_feats)

        # ─── Module 3.3 : Prev Levels (18 features) ───
        prev_feats = self._prev_levels.update(
            bar_ts_utc=bar_ts_utc,
            bar_high=sierra_bar.get("bar_high"),
            bar_low=sierra_bar.get("bar_low"),
            close=sierra_bar.get("close"),
            atr=sierra_bar.get("atr"),
        )
        enriched.update(prev_feats)

        # ─── Module 3.4 : Sessions Fine (35 features) ───
        sessions_feats = self._sessions_fine.update(
            bar_ts_utc=bar_ts_utc,
            bar_high=sierra_bar.get("bar_high"),
            bar_low=sierra_bar.get("bar_low"),
            close=sierra_bar.get("close"),
        )
        enriched.update(sessions_feats)

        # ─── Module 3.6 : Roll Calendar (3 features, stateless) ───
        try:
            roll_feats = compute_roll_features(
                bar_date=trading_date,
                symbol=self.symbol,
            )
            enriched.update(roll_feats)
        except ValueError:
            # Symbol non supporte (ex: MGC partial) -> NaN propre
            enriched.update({
                "is_roll_day": False,
                "days_since_roll": np.nan,
                "roll_phase": 0,
            })

        # ─── Module 3.7 : Eco News Features (10 features, stateless) ───
        try:
            eco_feats = compute_eco_news_features(now_utc=bar_ts_utc)
            enriched.update(eco_feats)
        except (RuntimeError, ValueError):
            # Module eco_calendar indispo (ex: tests sans network)
            enriched.update(self._empty_eco_features())

        # ─── Module 3.8 : Divergences V2 (14 features) ───
        div_feats = self._divergences_v2.update(
            close=sierra_bar.get("close"),
            delta_bar=sierra_bar.get("delta_bar"),
            atr=sierra_bar.get("atr"),
        )
        enriched.update(div_feats)

        # ─── Module 3.5 : Ctx Rolling CRITIQUE (25 features) ───
        ctx_feats = self._ctx_rolling.update(
            close=sierra_bar.get("close"),
            bar_high=sierra_bar.get("bar_high"),
            bar_low=sierra_bar.get("bar_low"),
            delta_bar=sierra_bar.get("delta_bar"),
            total_vol=sierra_bar.get("total_vol"),
            atr=sierra_bar.get("atr"),
            buy_vol=sierra_bar.get("buy_vol"),
            sell_vol=sierra_bar.get("sell_vol"),
            vwap_d=sierra_bar.get("vwap_d"),
            finish_strength=sierra_bar.get("finish_strength"),
            range_pos=sierra_bar.get("range_pos"),
            va_position_pct=sierra_bar.get("va_position_pct"),
            bn_absorb_ask=sierra_bar.get("bn_absorb_ask", 0.0) or 0.0,
            bn_absorb_bid=sierra_bar.get("bn_absorb_bid", 0.0) or 0.0,
        )
        enriched.update(ctx_feats)

        # Meta orchestrateur
        enriched["_phase3_enriched"] = True
        enriched["_phase3_bars_processed"] = self._bars_processed

        return enriched

    def _maybe_cross_day_reset(self, trading_date: date) -> bool:
        """Reset cross-day si trading_date change. Returns True si reset effectue."""
        if self._current_trading_date is None:
            self._current_trading_date = trading_date
            return False
        if trading_date == self._current_trading_date:
            return False
        # Cross-day : reset tous les Calculator stateful
        # (prev_levels + sessions_fine ont leur propre reset interne via ts,
        # mais on appelle pour safety + pour les autres)
        self._poc_migration.reset()
        self._swings_v2.reset()
        self._divergences_v2.reset()
        self._ctx_rolling.reset()
        # prev_levels et sessions_fine se reset automatiquement
        self._current_trading_date = trading_date
        return True

    @staticmethod
    def _extract_ts_utc(sierra_bar: dict) -> datetime:
        """Extrait timestamp UTC depuis sierra_bar.

        Cherche dans cet ordre :
          1. ts_utc (ISO string ou datetime)
          2. ts_event_ns (Databento format)
          3. ts (Sierra DMP format)

        Raises:
            ValueError : si aucun timestamp trouve.
        """
        for key in ("ts_utc", "ts_event_ns", "ts"):
            if key not in sierra_bar:
                continue
            v = sierra_bar[key]
            if v is None:
                continue
            if isinstance(v, datetime):
                return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
            if isinstance(v, str):
                # ISO format
                return datetime.fromisoformat(v.replace("Z", "+00:00"))
            if isinstance(v, (int, float)):
                # Heuristique multi-unite (Sierra DMP = ms, Databento = ns) :
                #   v > 1e17 -> nanoseconds (Databento ts_event_ns)
                #   v > 1e14 -> microseconds
                #   v > 1e11 -> milliseconds (Sierra DMP "ts")
                #   sinon   -> seconds
                if key == "ts_event_ns" or v > 1e17:
                    return datetime.fromtimestamp(v / 1e9, tz=timezone.utc)
                if v > 1e14:
                    return datetime.fromtimestamp(v / 1e6, tz=timezone.utc)
                if v > 1e11:
                    return datetime.fromtimestamp(v / 1e3, tz=timezone.utc)
                return datetime.fromtimestamp(v, tz=timezone.utc)
        raise ValueError(
            "SierraPipelineOrchestrator : impossible d'extraire timestamp UTC "
            "depuis sierra_bar (chercher ts_utc / ts_event_ns / ts)"
        )

    @staticmethod
    def _empty_eco_features() -> dict:
        """Empty features eco_news (fallback si module indispo)."""
        return {
            "is_news_5m": False,
            "is_news_15m": False,
            "is_news_30m": False,
            "is_news_60m": False,
            "is_critical_news_60m": False,
            "news_seconds_until": np.nan,
            "news_minutes_until": np.nan,
            "is_eco_blocked": False,
            "is_session_blocked": False,
            "is_blocked_combined": False,
        }

    def get_stats(self) -> dict:
        """Statistiques orchestrateur (monitoring + debug)."""
        return {
            "symbol": self.symbol,
            "bars_processed": self._bars_processed,
            "bars_skipped_nan": self._bars_skipped_nan,
            "cross_day_resets": self._cross_day_resets,
            "current_trading_date": (
                self._current_trading_date.isoformat()
                if self._current_trading_date else None
            ),
        }


def enrich_batch_dataframe(
    df: pd.DataFrame,
    symbol: str = "NQ",
    ts_col: str = "ts_utc",
) -> pd.DataFrame:
    """Batch enrichment Sierra historique (mode dataset_builder).

    Args:
        df : DataFrame avec bars Sierra natif (380 cols schema 3.7.22).
             Trie chronologiquement (ts_utc croissant).
        symbol : "ES" / "NQ" / "MGC".
        ts_col : nom colonne timestamp UTC.

    Returns:
        DataFrame copie + 113 colonnes Phase 3 ajoutees.

    Raises:
        ValueError : si ts_col manquant.
    """
    if ts_col not in df.columns:
        raise ValueError(
            f"enrich_batch_dataframe : colonne ts_utc '{ts_col}' manquante"
        )

    pipeline = SierraPipelineOrchestrator(symbol=symbol)
    rows = []

    for _, row in df.iterrows():
        sierra_bar = row.to_dict()
        ts = row[ts_col]
        if pd.isna(ts):
            # Skip bar invalide, append vide
            rows.append(sierra_bar)
            continue
        if isinstance(ts, str):
            bar_ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        elif isinstance(ts, (datetime, pd.Timestamp)):
            bar_ts = pd.Timestamp(ts).to_pydatetime()
            if bar_ts.tzinfo is None:
                bar_ts = bar_ts.replace(tzinfo=timezone.utc)
        else:
            rows.append(sierra_bar)
            continue
        enriched = pipeline.enrich_bar(sierra_bar, bar_ts_utc=bar_ts)
        rows.append(enriched)

    return pd.DataFrame(rows)
