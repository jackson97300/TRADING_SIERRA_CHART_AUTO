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
    from CORE.menthorq_v2_sierra_proxy import inject_gamma_condition_proxy
    from CORE.aggressor_imbalance_proxy import inject_aggressor_imbalance_proxy
    # Phase 1 Group A - portage modules Phase B+
    from CORE.phase_b_plus_long_streaming import (
        add_phase_b_plus_long_streaming, make_long_bar_state
    )
    from CORE.phase_b_plus_color_streaming import (
        add_phase_b_plus_color_streaming, make_color_bar_state
    )
    from CORE.bn_composites_streaming import inject_bn_composites
    # Phase 1 Group B - rolling_features (5 sub-engines, 35 ctx_* features)
    from CORE.rolling_features_streaming import (
        RollingFeaturesState,
        add_rolling_features_basic_streaming,
        add_rolling_features_medium_streaming,
        add_rolling_features_advanced_streaming,
        add_rolling_features_delta_div_streaming,
        add_rolling_features_session_confluence_streaming,
    )
    # Phase 1 Group B - edge_zones (alias Sierra natif + buffer pour n_active)
    from CORE.extension_lines_manager import ExtensionLineBuffer
    # Phase 1 Group C - rvol_engine (10 features rvol_*)
    from CORE.rvol_streaming import (
        add_rvol_engine_streaming, RvolEngineState
    )
    # Phase 1 Group D - intermarket (10 features cross-sym ES/NQ)
    from CORE.intermarket_streaming import (
        add_intermarket_streaming, IntermarketState
    )
    # Phase 1 D2 - phase_b_helpers (5 sub-engines, ordre IMPOSE)
    from CORE.phase_b_helpers import (
        SessionMetadataState, IBState, SessionHighLowState,
        OpenCashPrice1030State, IbAtrState,
        add_session_metadata_streaming,
        add_ib_features_streaming,
        add_session_high_low_streaming,
        add_open_cash_price1030_streaming,
        add_ib_atr_streaming,
    )
    # Phase 1 D2 - game_changers (5 features ressuscitees post phase_b_helpers)
    from CORE.game_changers_streaming import (
        add_game_changers_streaming, GameChangersState
    )
    # Phase 1.5 - Normalisation ts (fix jitter +/-1s Sierra natif, INCIDENT #48)
    from CORE.sierra_ts import normalize_payload_ts
    # Phase A.2a + A.3 - Market Profile + ICT/Wyckoff enrichment
    from CORE.market_profile_v5 import (
        compute_market_profile_v5_features, FVGState
    )
    from CORE.market_profile_advanced import (
        compute_market_profile_advanced_features, MarketProfileAdvancedState
    )
except ImportError:
    # Fallback si on lance depuis CORE/ directement
    from poc_migration import POCMigrationCalculator
    from swings_v2 import SwingsV2Calculator
    from prev_levels import PrevLevelsCalculator
    from sessions_fine import SessionsFineCalculator
    from divergences_v2 import DivergencesV2Calculator
    from ctx_rolling import CtxRollingCalculator
    from roll_calendar import compute_roll_features
    from sierra_ts import normalize_payload_ts  # type: ignore
    from market_profile_v5 import (  # type: ignore
        compute_market_profile_v5_features, FVGState
    )
    from market_profile_advanced import (  # type: ignore
        compute_market_profile_advanced_features, MarketProfileAdvancedState
    )
    from eco_news_features import compute_eco_news_features
    from session_utils import get_trading_date_from_utc, utc_to_et
    from menthorq_v2_sierra_proxy import inject_gamma_condition_proxy
    from aggressor_imbalance_proxy import inject_aggressor_imbalance_proxy
    # Phase 1 Group A
    from phase_b_plus_long_streaming import (
        add_phase_b_plus_long_streaming, make_long_bar_state
    )
    from phase_b_plus_color_streaming import (
        add_phase_b_plus_color_streaming, make_color_bar_state
    )
    from bn_composites_streaming import inject_bn_composites
    # Phase 1 Group B
    from rolling_features_streaming import (
        RollingFeaturesState,
        add_rolling_features_basic_streaming,
        add_rolling_features_medium_streaming,
        add_rolling_features_advanced_streaming,
        add_rolling_features_delta_div_streaming,
        add_rolling_features_session_confluence_streaming,
    )
    from extension_lines_manager import ExtensionLineBuffer
    # Phase 1 Group C - rvol_engine
    from rvol_streaming import (
        add_rvol_engine_streaming, RvolEngineState
    )
    # Phase 1 Group D - intermarket
    from intermarket_streaming import (
        add_intermarket_streaming, IntermarketState
    )
    # Phase 1 D2 - phase_b_helpers
    from phase_b_helpers import (
        SessionMetadataState, IBState, SessionHighLowState,
        OpenCashPrice1030State, IbAtrState,
        add_session_metadata_streaming,
        add_ib_features_streaming,
        add_session_high_low_streaming,
        add_open_cash_price1030_streaming,
        add_ib_atr_streaming,
    )
    from game_changers_streaming import (
        add_game_changers_streaming, GameChangersState
    )


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

    def __init__(self, symbol: str = "NQ", log_event=None) -> None:
        """
        Args:
            symbol     : ES / NQ / MGC / GC.
            log_event  : Callable(code: str, **kwargs) | None.
                Si fourni, propage aux proxies (gamma_condition, aggressor) pour
                tracabilite J+1 (regle souveraine Jackson 01/05/2026 LOGS
                TRACABILITE). Si None, les proxies ne logguent rien (mode
                offline batch).
        """
        self.symbol = symbol.upper()
        self.tick_size = DEFAULT_TICK_SIZE_BY_SYMBOL.get(self.symbol, 0.25)

        # Log callback pour proxies (Phase 5.0.A + 5.0.B)
        self._log_event = log_event

        # Initialize stateful calculators
        self._poc_migration = POCMigrationCalculator()
        self._swings_v2 = SwingsV2Calculator(tick_size=self.tick_size)
        self._prev_levels = PrevLevelsCalculator()
        self._sessions_fine = SessionsFineCalculator()
        self._divergences_v2 = DivergencesV2Calculator()
        self._ctx_rolling = CtxRollingCalculator()
        # Phase A.2a + A.3 - Market Profile + ICT/Wyckoff enrichment states
        # Stateful : FVG (state machine 3-bar rolling)
        # Stateful : Composite POC (rolling 5/20 daily VPOCs)
        # Stateful : Liquidity Sweep (rolling N-bar + active sweeps tracking)
        # Stateful : Judas Swing (London session entry/exit)
        # Stateless : Single Prints (calcul instantane), PSD+2/-2, Open Relation,
        #             Profile Overlap, Range Extension (calcul instantane).
        # State per-symbol (orchestrator instancie par symbol = isolation ES/NQ).
        self._fvg_state = FVGState()
        self._market_profile_advanced_state = MarketProfileAdvancedState()

        # Cross-day tracking
        self._current_trading_date: Optional[date] = None

        # Phase 1 Group A - cvd_session minimal (fix C2 bug NULL)
        # cumsum delta_bar reset par session. Reset au cross-day.
        # Cf rolling_features_streaming.py:1170-1179 (sera porte Group B).
        self._cvd_session_running: float = 0.0

        # Phase 1 Group A - portage modules Phase B+ streaming
        self._long_bar_state = make_long_bar_state(self.symbol)
        self._color_bar_state = make_color_bar_state(self.symbol)

        # Phase 1 Group B - rolling_features state (5 sub-engines)
        self._rolling_state = RollingFeaturesState()
        # Phase 1 Group B - edge_zones extension buffers (Sierra natif + n_active)
        # Sierra DMP fire bar_edge_buy/sell (binaire) mais ne maintient pas
        # n_active count. ExtensionLineBuffer track les zones active jusqu'a
        # touche par bar high/low (mirror logique batch edge_zones_engine).
        self._edge_buy_buffer = ExtensionLineBuffer()
        self._edge_sell_buffer = ExtensionLineBuffer()
        self._edge_bar_idx = 0
        # Phase 1 Group B - delta_div : pas de state additionnel
        # (divergences_v2 Calculator Phase 3 le gere natif)

        # Phase 1 Group C - rvol_engine state (10 features rvol_*)
        # Inputs requis Sierra natif : total_vol, delta_pct, finish_strength, ts (ms).
        # Sierra DMP emet 6 features natif (rvol, rvol_zscore, rvol_buy, rvol_sell,
        # rvol_absorb_buy, rvol_absorb_sell). Python ajoute 4 features UNIQUES :
        # rvol_regime, rvol_buy_strong, rvol_sell_strong, rvol_extreme.
        #
        # MECANISME PRESERVATION SIERRA (review code-reviewer 11/06 MUST-HAVE #1) :
        # La preservation des 6 keys Sierra natifs N'utilise PAS _safe_update
        # (_safe_update preserve UNIQUEMENT si phase3_v est NaN/None).
        # Elle utilise `produced = set(rvol_out) - set(row_for_rvol)` ligne 720 :
        # les keys deja dans row_for_rvol (= enriched = Sierra) sont EXCLUES
        # du merge. Mecanisme valide mais FRAGILE : si refactor de
        # add_rvol_engine_streaming change `out = dict(row)` -> `out = {}`, ou si
        # quelqu'un fait `del row["rvol"]`, regression silencieuse possible.
        self._rvol_state = RvolEngineState()

        # Phase 1 Group D - intermarket state + buffer partner bar (cross-sym)
        # Sierra DMP n'emet AUCUNE feature im_* native -> port complet necessaire.
        # Caller (live_pipeline ou tests) doit appeler `set_partner_bar(bar)`
        # AVANT enrich_bar pour fournir le bar du partenaire ES<->NQ.
        # Sans partner_bar : other_inputs=None -> 10 features im_* = NaN propre.
        # Staleness check : reject partner si > 120s old ou future timestamp.
        self._intermarket_state = IntermarketState()
        self._partner_bar: Optional[dict] = None

        # Phase 1 D2 - phase_b_helpers states (5 sub-engines, ORDRE IMPOSE)
        # 1. session_metadata -> date_et, mins_et, session_date_trading,
        #    is_cash_session, is_ib_window
        # 2. ib_features -> ib_high/low, ib_complete, ib_range_ticks, etc.
        #    REQUIERT date_et + mins_et + is_ib_window (raise ValueError sinon)
        # 3. session_high_low -> sess_high/low absolus
        # 4. open_cash_price1030 -> open_cash, price_1030, above_open_*
        # 5. ib_atr -> ib_atr_python (rename anti-collision Sierra atr natif)
        # Skip volume_profile (5) et rvol_inputs (6) : Sierra natif emet deja
        # equivalents (16+ features cur/prev_vah/val/vpoc, delta_pct,
        # finish_strength, range_size).
        self._sm_state = SessionMetadataState()
        self._ib_state = IBState()
        self._shl_state = SessionHighLowState()
        self._ocp_state = OpenCashPrice1030State()
        self._ib_atr_state = IbAtrState()
        # Phase 1 D2 - game_changers (5 features ressuscitees)
        # Inputs requis : date_et + mins_et + open_cash + prev_vah/val/vpoc +
        # ib_high/low + sess_high/low + close + price_1030 + pdh/pdl
        # Apres aliases _lvl + chain phase_b_helpers, tous dispos.
        self._gc_state = GameChangersState()

        # Stats orchestrateur (debug + monitoring)
        self._bars_processed: int = 0
        self._bars_skipped_nan: int = 0
        self._cross_day_resets: int = 0

        # Stats proxies Phase 5.0 (fix C2 review code-reviewer 11/06)
        # Permet monitoring J+1 % bars proxy-active
        self._proxy_gamma_injected: int = 0
        self._proxy_gamma_skipped: int = 0
        self._proxy_gamma_preserved: int = 0
        self._proxy_aggressor_injected: int = 0
        self._proxy_aggressor_skipped: int = 0
        self._proxy_aggressor_preserved: int = 0

    def _proxy_log_wrapper(self, code: str, **kwargs) -> None:
        """Wrapper propre counters + forward au log_event externe.

        Incremente les counters pour monitoring J+1, puis emit via log_event
        si fourni. Pattern : compter d'abord, logger ensuite (counters fiables
        meme si log_event raise).
        """
        if code == "MQ_PROXY_INJECTED":
            self._proxy_gamma_injected += 1
        elif code == "MQ_PROXY_SKIPPED_NO_FLIP_ZONE":
            self._proxy_gamma_skipped += 1
        elif code == "MQ_PROXY_PRESERVED_ORIGINAL":
            self._proxy_gamma_preserved += 1
        elif code == "AGGRESSOR_PROXY_INJECTED":
            self._proxy_aggressor_injected += 1
        elif code == "AGGRESSOR_PROXY_SKIPPED_MISSING_INPUTS":
            self._proxy_aggressor_skipped += 1
        elif code == "AGGRESSOR_PROXY_PRESERVED_ORIGINAL":
            self._proxy_aggressor_preserved += 1

        if self._log_event is not None:
            try:
                self._log_event(code, **kwargs)
            except Exception:  # noqa: BLE001
                pass  # log non-bloquant

    def get_proxy_stats(self) -> dict:
        """Stats proxies pour monitoring J+1 (fix C2 review).

        Returns:
            dict : counters par proxy + total bars + % rate.
        """
        total = max(self._bars_processed, 1)
        return {
            "bars_processed": self._bars_processed,
            "gamma": {
                "injected": self._proxy_gamma_injected,
                "skipped": self._proxy_gamma_skipped,
                "preserved": self._proxy_gamma_preserved,
                "injected_pct": 100.0 * self._proxy_gamma_injected / total,
            },
            "aggressor": {
                "injected": self._proxy_aggressor_injected,
                "skipped": self._proxy_aggressor_skipped,
                "preserved": self._proxy_aggressor_preserved,
                "injected_pct": 100.0 * self._proxy_aggressor_injected / total,
            },
        }

    # ─── Whitelist features Sierra placeholders (Phase 0 design v2 B3 + B5) ───
    # Features ou Sierra DMP emet 0/placeholder cassé. Python override autoritatif.
    # Cf DMP_Transform.h:1414-1416 (bn_score_* hardcoded 0.0f volontaire) +
    # 15/MIA_PIPELINE_RECAP.md:434 (trend_day_probability DEAD historique).
    # Decision Jackson 11/06 : BN famille recodee Python pour controle (override
    # verdict 2 agents) - documenter PATTERN_11 vigilance si gate hardcode propose.
    SIERRA_ZERO_NEVER_CALCULATED = frozenset((
        # B3 - bn_score_* placeholder C++ DMP_Transform.h:1397 (desactive 18/04)
        "bn_score_raw", "bn_score_bull", "bn_score_bear",
        # NB : bn_pressure_ask/bid RETIRES de la whitelist 11/06 - signal Sierra
        # VIVANT cf DMP_Transform.h:1393-1395 (Double/Triple Ask). Verif empirique
        # 20260605_ES.jsonl : 0.5%/1.2% bars non-zero. Override Python interdit.
        # B5 - game_changers placeholders Sierra DMP (decision post-Jackson)
        "trend_day_probability",   # remplace downstream par ctx_trend_day_score
        "open_direction",           # recalcul via game_changers.direction()
    ))

    @classmethod
    def _safe_update(cls, enriched: dict, phase3_feats: dict) -> None:
        """Update enriched avec phase3_feats SANS ecraser valeurs Sierra natif non-NaN.

        Fix B6 audit ULTRATHINK 11/06 : Sierra DMP calcule deja certaines
        features (pdh, pdl, ovn_high, asia_high, etc.). Phase 3 Calculator
        re-calculent et retournent NaN/None pendant cold-start, ce qui ECRASE
        les valeurs Sierra correctes.

        Politique :
        - Si Phase 3 retourne None/NaN ET Sierra natif a une valeur, garder Sierra.
        - Sinon utiliser Phase 3 (incluant False/0 explicit).
        - EXCEPTION (Phase 0 B3+B5) : features dans SIERRA_ZERO_NEVER_CALCULATED
          ou Sierra=0.0 est un placeholder casse -> Python override autoritatif
          meme si Phase 3 retourne valeur non-None.
        """
        import math
        for k, phase3_v in phase3_feats.items():
            existing = enriched.get(k)
            # Phase 3 returns NaN/None -> garder Sierra si vivant
            is_p3_nan = (phase3_v is None or
                         (isinstance(phase3_v, float) and math.isnan(phase3_v)))

            # EXCEPTION B3+B5 : Sierra placeholder 0.0 → Python override autoritatif
            if (k in cls.SIERRA_ZERO_NEVER_CALCULATED
                and existing == 0.0
                and not is_p3_nan):
                enriched[k] = phase3_v
                continue

            # Politique standard
            if is_p3_nan and existing is not None:
                continue  # garde Sierra natif
            enriched[k] = phase3_v

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

        # FIX BUG #1 audit ULTRATHINK 11/06 : DMP utilise 'price' (pas 'close').
        # Mapping pour Calculator + PERSIST dans enriched (sans persist :
        # downstream Bot 1 V3 / train_lightgbm qui lit bar['close'] casse).
        close = sierra_bar.get("close")
        if close is None:
            close = sierra_bar.get("price")
        bar_high = sierra_bar.get("bar_high") or sierra_bar.get("high")
        bar_low = sierra_bar.get("bar_low") or sierra_bar.get("low")
        total_vol = sierra_bar.get("total_vol")
        if total_vol is None:
            total_vol = sierra_bar.get("volume")

        # Persiste alias dans enriched (fix B1 review code-reviewer + fix Jackson 11/06).
        # Double-aliases pour consumers legacy : 'close'/'price', 'bar_high'/'high',
        # 'bar_low'/'low', 'total_vol'/'volume'. Sans ca, Bot3v4 fait row.get("high")
        # et recoit None alors que bar_high existe.
        if close is not None:
            enriched["close"] = close
            enriched["price"] = close  # alias Sierra DMP natif
        if bar_high is not None:
            enriched["bar_high"] = bar_high
            enriched["high"] = bar_high  # alias Bot3v4 + consumers legacy Databento
        if bar_low is not None:
            enriched["bar_low"] = bar_low
            enriched["low"] = bar_low
        if total_vol is not None:
            enriched["total_vol"] = total_vol
            enriched["volume"] = total_vol

        # ─── Module 3.1 : POC Migration (2 features) ───
        poc_feats = self._poc_migration.update(
            dist_cur_vpoc=sierra_bar.get("dist_cur_vpoc"),
        )
        self._safe_update(enriched,poc_feats)

        # ─── Module 3.2 : Swings V2 Wyckoff/ICT (6 features) ───
        # Fix P2 audit market-analyst + quality-auditor 11/06 :
        # Sierra DMP fournit `new_swing_high/low` natif (18 et 32 events sur 1926
        # bars NQ). Code Phase 3 essayait de detecter via `dist_swing_high == 0`
        # mais Sierra ne reset jamais dist a 0 sur la bar swing -> high DEAD.
        # Bug asymetrique : low fonctionnait par chance (4 zeros aleatoires).
        # Si Sierra fournit new_swing_high/low : substituer dist=0 force pour
        # declencher detection Phase 3.
        dsh = sierra_bar.get("dist_swing_high")
        dsl = sierra_bar.get("dist_swing_low")
        if sierra_bar.get("new_swing_high"):
            dsh = 0.0  # force detection cote Phase 3
        if sierra_bar.get("new_swing_low"):
            dsl = 0.0

        swings_feats = self._swings_v2.update(
            dist_swing_high=dsh,
            dist_swing_low=dsl,
            bar_high=bar_high,
            bar_low=bar_low,
            close=close,
        )
        self._safe_update(enriched,swings_feats)

        # ─── Module 3.3 : Prev Levels (18 features) ───
        prev_feats = self._prev_levels.update(
            bar_ts_utc=bar_ts_utc,
            bar_high=bar_high,
            bar_low=bar_low,
            close=close,
            atr=sierra_bar.get("atr"),
        )
        self._safe_update(enriched,prev_feats)

        # ─── Module 3.4 : Sessions Fine (35 features) ───
        sessions_feats = self._sessions_fine.update(
            bar_ts_utc=bar_ts_utc,
            bar_high=bar_high,
            bar_low=bar_low,
            close=close,
        )
        self._safe_update(enriched,sessions_feats)

        # ─── Module 3.6 : Roll Calendar (3 features, stateless) ───
        try:
            roll_feats = compute_roll_features(
                bar_date=trading_date,
                symbol=self.symbol,
            )
            self._safe_update(enriched,roll_feats)
        except ValueError:
            # Symbol non supporte (ex: MGC partial) -> NaN propre
            self._safe_update(enriched,{
                "is_roll_day": False,
                "days_since_roll": np.nan,
                "roll_phase": 0,
            })

        # ─── Module 3.7 : Eco News Features (10 features, stateless) ───
        try:
            eco_feats = compute_eco_news_features(now_utc=bar_ts_utc)
            self._safe_update(enriched,eco_feats)
        except (RuntimeError, ValueError):
            # Module eco_calendar indispo (ex: tests sans network)
            self._safe_update(enriched,self._empty_eco_features())

        # ─── Module 3.8 : Divergences V2 (14 features) ───
        div_feats = self._divergences_v2.update(
            close=close,
            delta_bar=sierra_bar.get("delta_bar"),
            atr=sierra_bar.get("atr"),
        )
        self._safe_update(enriched,div_feats)

        # ─── Module 3.5 : Ctx Rolling CRITIQUE (25 features) ───
        # Fix BUG #2 + #3 audit ULTRATHINK 11/06 :
        # - Sierra DMP utilise `range_pos_va` (Value Area position), pas `range_pos`.
        # - Sierra emit en SCALE [0, 100] (pourcentage). Le code ctx_rolling
        #   utilise seuils RANGE_POS_EXTREME_HIGH=0.9 / LOW=0.1 (scale [0,1]).
        # Sans normalisation /100 : seuil 0.9 declenche sur ~70% des bars
        # (faux positifs climax). Verification empirique 11/06 NQ.
        range_pos = sierra_bar.get("range_pos")
        if range_pos is None:
            range_pos = sierra_bar.get("range_pos_va")
        # Auto-detect scale : si max observe > 1.5 = [0,100], normaliser /100
        if range_pos is not None and range_pos > 1.5:
            range_pos = range_pos / 100.0

        ctx_feats = self._ctx_rolling.update(
            close=close,
            bar_high=bar_high,
            bar_low=bar_low,
            delta_bar=sierra_bar.get("delta_bar"),
            total_vol=total_vol,
            atr=sierra_bar.get("atr"),
            buy_vol=sierra_bar.get("buy_vol"),
            sell_vol=sierra_bar.get("sell_vol"),
            vwap_d=sierra_bar.get("vwap_d"),
            finish_strength=sierra_bar.get("finish_strength"),
            range_pos=range_pos,
            va_position_pct=sierra_bar.get("va_position_pct"),
            bn_absorb_ask=sierra_bar.get("bn_absorb_ask", 0.0) or 0.0,
            bn_absorb_bid=sierra_bar.get("bn_absorb_bid", 0.0) or 0.0,
        )
        self._safe_update(enriched,ctx_feats)

        # ─── Phase 5.0.A : Proxy MenthorQ Sierra-native (11/06/2026) ───
        # Scraper MenthorQ down depuis 27/05 -> mq_gamma_condition absent.
        # MQ API publique non encore dispo (Jackson liste d'attente).
        # Proxy temporaire : bool_gex_flip_zone (Sierra DMP natif) -> mq_gamma_condition.
        # Cf CORE/menthorq_v2_sierra_proxy.py docstring pour semantique + revert.
        # Fix C1 review 11/06 : log_fn + sym branches pour tracabilite J+1.
        inject_gamma_condition_proxy(
            enriched, log_fn=self._proxy_log_wrapper, sym=self.symbol)

        # ─── Phase 5.0.B : Proxy aggressor_imbalance Sierra-native (11/06/2026) ───
        # Sierra DMP ne fournit pas trade-by-trade aggressor count (PhaseB+ original).
        # Reconstruction count via buy_vol/avg_ask_size + sell_vol/avg_bid_size
        # pour preserver semantique COUNT (vs ask_bid_imbalance volume-weighted).
        # Cf CORE/aggressor_imbalance_proxy.py docstring.
        inject_aggressor_imbalance_proxy(
            enriched, log_fn=self._proxy_log_wrapper, sym=self.symbol)

        # ─── Phase 1 Group A - cvd_session minimal (fix C2 bug NULL) ───
        # cumsum delta_bar reset par cross-day. Convention Sierra confirmee :
        # delta_bar Sierra natif = AskVolume - BidVolume (signe sain post fix 07/06).
        # cvd_session est consomme par bot3_context_analyzer.py:95.
        # NB : portage complet rolling_features_streaming Group B remplacera ce fix.
        delta_bar = sierra_bar.get("delta_bar")
        if delta_bar is not None:
            try:
                self._cvd_session_running += float(delta_bar)
                enriched["cvd_session"] = round(self._cvd_session_running, 2)
            except (TypeError, ValueError):
                pass

        # ─── Phase 1 Group A - phase_b_plus_long_streaming (13 features) ───
        # bn_long_up/dn, bar_body_ticks, range_*, long_*_pattern, extension lines.
        # Necessite open/high/low/close dans enriched (aliases F2 deja faits).
        try:
            long_out = add_phase_b_plus_long_streaming(
                enriched, self._long_bar_state)
            # _safe_update merge avec gestion NaN + whitelist
            self._safe_update(enriched, {k: long_out[k] for k in long_out
                                          if k not in enriched})
            if self._log_event is not None:
                try:
                    self._log_event("SIERRA_PORT_PHASE_B_PLUS_LONG_OK",
                                     sym=self.symbol)
                except Exception:  # noqa: BLE001
                    pass
        except Exception as _e:  # noqa: BLE001
            if self._log_event is not None:
                try:
                    self._log_event("SIERRA_PORT_PHASE_B_PLUS_LONG_FAIL",
                                     sym=self.symbol, err=str(_e)[:200])
                except Exception:  # noqa: BLE001
                    pass

        # ─── Phase 1 Group A - phase_b_plus_color_streaming (12 features lag-1) ───
        # dist_color_*_pct, n_color_*_cluster (consomme par Bot 3 v3 wrapper).
        try:
            color_out = add_phase_b_plus_color_streaming(
                enriched, self._color_bar_state)
            self._safe_update(enriched, {k: color_out[k] for k in color_out
                                          if k not in enriched})
            if self._log_event is not None:
                try:
                    self._log_event("SIERRA_PORT_COLOR_BARS_OK",
                                     sym=self.symbol)
                except Exception:  # noqa: BLE001
                    pass
        except Exception as _e:  # noqa: BLE001
            if self._log_event is not None:
                try:
                    self._log_event("SIERRA_PORT_COLOR_BARS_FAIL",
                                     sym=self.symbol, err=str(_e)[:200])
                except Exception:  # noqa: BLE001
                    pass

        # ─── Phase 1 Group A - bn_composites Python (B3 decision Jackson) ───
        # Sierra DMP emet bn_score_* a 0.0 (desactive 18/04/2026 cf DMP_Transform.h:1397).
        # Python recalcule UNIQUEMENT bn_score_raw/bull/bear (PAS bn_pressure_*
        # qui sont Sierra natifs vivants cf DMP_Transform.h:1393-1395).
        # Route via _safe_update strict (whitelist SIERRA_ZERO_NEVER_CALCULATED).
        # PATTERN_11 vigilance : ne PAS hardcoder gate sur bn_score_X sans DSR.
        inject_bn_composites(enriched, safe_update_fn=self._safe_update,
                              log_fn=self._log_event, sym=self.symbol)

        # ─── Phase 1 Group B - rolling_features (5 sub-engines, 35+ ctx_*) ───
        # Pattern mirror enricher_chain.py:1071-1105 Databento. Aliases requis :
        # - 'ts' en MILLISECONDES (delta_div module utilise pour trading_date CME)
        # - 'price' alias close, 'bar_high'/'bar_low' alias high/low
        # Merge par DIFF de cles (pas whitelist) pour capturer toutes les
        # features produites par les 5 sub-engines.
        try:
            ts_event_ns = sierra_bar.get("ts_event_ns") or int(
                bar_ts_utc.timestamp() * 1_000_000_000)
            row_for_rolling = dict(enriched)
            if "price" not in row_for_rolling and "close" in row_for_rolling:
                row_for_rolling["price"] = row_for_rolling["close"]
            row_for_rolling["ts"] = ts_event_ns / 1_000_000
            if "bar_high" not in row_for_rolling and "high" in row_for_rolling:
                row_for_rolling["bar_high"] = row_for_rolling["high"]
            if "bar_low" not in row_for_rolling and "low" in row_for_rolling:
                row_for_rolling["bar_low"] = row_for_rolling["low"]
            # Phase 2.2 (12/06/2026 PM) : refactor delta_div_* coherence.
            #
            # AVANT (FIX M1) : sub-engine #4 add_rolling_features_delta_div_streaming
            # recalculait CUMMAX et ecrasait delta_div_*_clean dans `er`.
            # Sub-engine #5 session_confluence LISAIT cette version CUMMAX pour
            # calculer ctx_div_density_20, ctx_bars_since_div, ctx_div_at_swing,
            # div_at_key_level_ticks, div_confluence_dmp, div_confluence_with_regime.
            # Resultat MISMATCH SILENCIEUX LIVE : delta_div_*_clean final = SLOPE
            # (protege par set-diff), ctx_div_* = CUMMAX.
            # Le fix M1 forcait row_for_rolling[delta_div_*_clean] = SLOPE mais
            # sub-engine #4 ecrasait apres -> fix incomplet.
            #
            # APRES Phase 2.2 : SUPPRESSION sub-engine #4 + fix M1.
            # divergences_v2.update() ecrit delta_div_*_clean SLOPE dans
            # enriched en amont (ligne 533-538). row_for_rolling = dict(enriched)
            # contient SLOPE. Sub-engine #5 lit row["delta_divergence_clean"]
            # = SLOPE directement. Coherence interne LIVE garantie.
            #
            # Cf INCIDENT_LOG #51 + CORE/divergences_v2.py docstring complete.
            er = add_rolling_features_basic_streaming(row_for_rolling, self._rolling_state)
            er = add_rolling_features_medium_streaming(er, self._rolling_state)
            er = add_rolling_features_advanced_streaming(er, self._rolling_state)
            # PHASE 2.2 : sub-engine #4 SUPPRIME (code dissimule CUMMAX,
            # cf INCIDENT_LOG #51). Sub-engine #5 lit directement SLOPE.
            er = add_rolling_features_session_confluence_streaming(er, self._rolling_state)
            # Merge DIFF de cles uniquement (evite ecrasement)
            produced_keys = set(er) - set(row_for_rolling)
            self._safe_update(enriched, {k: er[k] for k in produced_keys})
            if self._log_event is not None:
                try:
                    self._log_event("SIERRA_PORT_ROLLING_FEATURES_OK", sym=self.symbol,
                                     n_produced=len(produced_keys))
                except Exception:  # noqa: BLE001
                    pass
        except Exception as _e:  # noqa: BLE001
            if self._log_event is not None:
                try:
                    self._log_event("SIERRA_PORT_ROLLING_FEATURES_FAIL",
                                     sym=self.symbol, err=str(_e)[:200])
                except Exception:  # noqa: BLE001
                    pass

        # ─── Phase 1 Group B - edge_zones n_active via Sierra fire + buffer ───
        # Sierra DMP fire bar_edge_buy/sell (binaire) + dist_edge_*_nearest_pct
        # natif. On COMPLETE avec n_edge_*_active via ExtensionLineBuffer.
        # Logique : si Sierra fire = 1, on add_zone a close. Buffer deactive
        # automatiquement les zones traversees par bar high/low.
        # ALIAS bar_edge_buy_fire = bar_edge_buy (compat consommateur BN V4).
        #
        # === RESERVE M2 review code-reviewer 11/06 ===
        # PERTE SEMANTIQUE vs batch edge_zones_engine.py :
        # - Batch add_zone(idx, stack_prices_consecutifs) -> epaisseur 4-15 ticks
        #   (groupe cellules VAP imbalance >= threshold). Zone vit plusieurs bars.
        # - Sierra-port add_zone(idx, [close]) -> epaisseur 0. Zone meurt en
        #   1-3 bars (bar future overlap close direct).
        # CONSEQUENCE : `n_edge_*_active` Sierra-port est CONSERVATIVE (~0-1)
        # vs batch (~5-15). Gates downstream sur `n_edge_*_active >= 1`
        # seront strictement plus restrictifs.
        # PATTERN_11 vigilance : NE PAS recalibrer seuils consumer en se basant
        # sur cette distribution Sierra-port sans verifier divergence vs batch
        # Databento (harness Phase 4 parity).
        # Affecte : bn_v4_engine.py:311,758 (gate BN V4), mia_paper_trader.py:2139
        # (observabilite). dataset_builder ML utilise bar_edge_*_zone_size que
        # ce port ne calcule PAS (epaisseur 0). Dataset offline non-bloqu.
        try:
            bar_high_f = enriched.get("bar_high") or enriched.get("high")
            bar_low_f = enriched.get("bar_low") or enriched.get("low")
            close_f = enriched.get("close")
            fire_buy = int(enriched.get("bar_edge_buy", 0) or 0)
            fire_sell = int(enriched.get("bar_edge_sell", 0) or 0)

            # 1. Update : deactive zones touchees
            if bar_high_f is not None and bar_low_f is not None:
                self._edge_buy_buffer.update_with_bar(
                    self._edge_bar_idx, float(bar_low_f), float(bar_high_f))
                self._edge_sell_buffer.update_with_bar(
                    self._edge_bar_idx, float(bar_low_f), float(bar_high_f))

            # 2. Add zone si Sierra fire
            if fire_buy == 1 and close_f is not None:
                self._edge_buy_buffer.add_zone(
                    self._edge_bar_idx, [float(close_f)], "buy")
            if fire_sell == 1 and close_f is not None:
                self._edge_sell_buffer.add_zone(
                    self._edge_bar_idx, [float(close_f)], "sell")

            # 3. Features : count active
            edge_out = {
                "bar_edge_buy_fire": fire_buy,
                "bar_edge_sell_fire": fire_sell,
                "n_edge_buy_active": self._edge_buy_buffer.count_active("buy"),
                "n_edge_sell_active": self._edge_sell_buffer.count_active("sell"),
            }
            self._safe_update(enriched, edge_out)
            self._edge_bar_idx += 1
            if self._log_event is not None:
                try:
                    self._log_event("SIERRA_PORT_EDGE_ZONES_OK", sym=self.symbol)
                except Exception:  # noqa: BLE001
                    pass
        except Exception as _e:  # noqa: BLE001
            if self._log_event is not None:
                try:
                    self._log_event("SIERRA_PORT_EDGE_ZONES_FAIL",
                                     sym=self.symbol, err=str(_e)[:200])
                except Exception:  # noqa: BLE001
                    pass

        # ─── Phase 1 Group B - delta_div : DEJA FAIT par divergences_v2 ─────
        # divergences_v2 Calculator (Phase 3) calcule 14 features delta_div_*
        # natif Python (slope-based Lopez-style) : delta_div_buy/sell,
        # delta_div_strength, n_delta_div_*_zones_active, dist_delta_div_*_atr,
        # retest_high/low_delta_div, ctx_div_density_20, ctx_bars_since_div.
        # Sierra natif `delta_divergence` reste accessible aux bots (BN V4 le
        # consume directement). Pas de portage add_delta_div_ext_streaming
        # (creerait doublon + ecrasement valeurs validees).

        # ─── Phase 1 Group C - rvol_engine (10 features rvol_*) ─────────────
        # Sierra DMP emet 6 features natif. Python add 4 UNIQUES via merge
        # set DIFF (produced exclut keys deja Sierra). Cf commentaire __init__.
        try:
            row_for_rvol = dict(enriched)
            # Convert ts ns -> ms si dispo
            if "ts" not in row_for_rvol:
                ts_ns = sierra_bar.get("ts_event_ns")
                if ts_ns is not None:
                    row_for_rvol["ts"] = ts_ns / 1_000_000
                else:
                    row_for_rvol["ts"] = bar_ts_utc.timestamp() * 1000
            # Capture Sierra rvol natifs AVANT sub-engine pour assert defensif
            _sierra_rvol_keys = ("rvol", "rvol_zscore", "rvol_buy", "rvol_sell",
                                   "rvol_absorb_buy", "rvol_absorb_sell")
            _sierra_rvol_before = {k: enriched.get(k) for k in _sierra_rvol_keys
                                     if k in enriched}
            rvol_out = add_rvol_engine_streaming(row_for_rvol, self._rvol_state)
            produced = set(rvol_out) - set(row_for_rvol)
            # ASSERT DEFENSIF review MUST #1 : keys Sierra ne sont pas dans produced
            # (si oui = regression mecanisme preservation set DIFF)
            _leaked = [k for k in _sierra_rvol_before if k in produced]
            if _leaked and self._log_event is not None:
                try:
                    self._log_event("SIERRA_PORT_RVOL_DEGRADED", sym=self.symbol,
                                     reason=f"sierra_keys_leaked={_leaked}")
                except Exception:  # noqa: BLE001
                    pass
            self._safe_update(enriched, {k: rvol_out[k] for k in produced})
            if self._log_event is not None:
                try:
                    self._log_event("SIERRA_PORT_RVOL_OK", sym=self.symbol)
                except Exception:  # noqa: BLE001
                    pass
        except Exception as _e:  # noqa: BLE001
            if self._log_event is not None:
                try:
                    self._log_event("SIERRA_PORT_RVOL_FAIL",
                                     sym=self.symbol, err=str(_e)[:200])
                except Exception:  # noqa: BLE001
                    pass

        # ─── Phase 1 Group C - Aliases big_v2 Sierra -> setup_engine compat ─
        # MUST-HAVE #2 review code-reviewer 11/06 :
        # setup_engine.py:490-491 (consume par databento_paper_trader_v2 PROD)
        # attend `n_big_ask_v2_t1..t4`, `n_big_bid_v2_t1..t4`,
        # `max_big_ask_vol_in_bar`, `max_big_bid_vol_in_bar`.
        # Sierra natif emet noms differents : `n_big_ask_t*` (sans `_v2_`) +
        # `max_ask_vol_in_bar` / `max_bid_vol_in_bar` (sans `_big_`).
        # SANS aliases : 8 features setup_engine = None silencieusement ->
        # bigtrader features DEAD apres switch Sierra (CONTEXT_MISS pattern).
        # PERTE SEMANTIQUE : Sierra `n_big_ask_t*` = cluster-based extension lines.
        # Python `n_big_ask_v2_t*` = cellule VAP count. Differents mais best-effort
        # car footprint_cells absent. Backtest A/B obligatoire avant trust live.
        # PATTERN_11 vigilance : NE PAS recalibrer seuils setup_engine bigtrader
        # sur cette distribution sans verifier divergence vs batch Databento.
        for _ti in (1, 2, 3, 4):
            _sierra_key = f"n_big_ask_t{_ti}"
            _v2_key = f"n_big_ask_v2_t{_ti}"
            if _v2_key not in enriched and _sierra_key in enriched:
                enriched[_v2_key] = enriched[_sierra_key]
            _sierra_key = f"n_big_bid_t{_ti}"
            _v2_key = f"n_big_bid_v2_t{_ti}"
            if _v2_key not in enriched and _sierra_key in enriched:
                enriched[_v2_key] = enriched[_sierra_key]
        # max_*_vol_in_bar alias
        if "max_big_ask_vol_in_bar" not in enriched and "max_ask_vol_in_bar" in enriched:
            enriched["max_big_ask_vol_in_bar"] = enriched["max_ask_vol_in_bar"]
        if "max_big_bid_vol_in_bar" not in enriched and "max_bid_vol_in_bar" in enriched:
            enriched["max_big_bid_vol_in_bar"] = enriched["max_bid_vol_in_bar"]

        # ─── Phase 1 Group C - C1/C2/C3 NON PORTES (besoin footprint_cells) ─
        # C1 big_v2 (10 features n_big_*_v2_t*) : aliases Sierra natif ci-dessus
        #    PARTIEL (8 features count + 2 max). Pas porte completement.
        # C2 cluster_v2 (5 features n_cluster_*) : requiert footprint_cells
        # C3 trapped_traders (10 features bn_trapped_*) : requiert footprint_cells
        #    + LOT 4 absorb (near_resistance_level, near_support_level) prerequis
        #    Audit prod 11/06 : aucun bot actif ne consume bn_trapped_* (verifie)
        # Sierra DMP n'expose pas trades_in_window stream -> aucun moyen de
        # construire footprint_cells sans modifier C++ (DEPLOY_UNSAFE).
        # Deferred Phase 1 Group D ou plus tard si A4 absorb prioritaire.

        # ─── Phase 1 D2 - aliases _lvl Sierra -> Python (game_changers compat) ─
        # Sierra DMP emet niveaux en suffixe `_lvl` (prev_vah_lvl, open_cash_lvl).
        # game_changers + bots downstream attendent noms sans suffixe.
        # Aliases sans ecrasement (preserve Sierra natif si deja set).
        for _k_lvl, _k in (("prev_vah_lvl", "prev_vah"),
                            ("prev_val_lvl", "prev_val"),
                            ("prev_vpoc_lvl", "prev_vpoc"),
                            ("cur_vah_lvl", "cur_vah"),
                            ("cur_val_lvl", "cur_val"),
                            ("cur_vpoc_lvl", "cur_vpoc"),
                            ("open_cash_lvl", "open_cash"),
                            ("open_830_lvl", "open_830"),
                            ("ovn_high_lvl", "ovn_high"),
                            ("ovn_low_lvl", "ovn_low")):
            _v = enriched.get(_k_lvl)
            if _v is not None and enriched.get(_k) is None:
                enriched[_k] = _v

        # ─── Phase 1 D2 - phase_b_helpers chain (5 sub-engines ORDRE IMPOSE) ─
        # Sequence : session_metadata -> ib_features -> session_high_low ->
        #            open_cash_price1030 -> ib_atr
        # Chaque sub-engine raise ValueError si ses inputs (date_et, etc.)
        # absents -> ordre IMPOSE critique.
        # Bouclier try/except global anti-crash live (mais log MAJEUR).
        try:
            import pandas as _pd
            # FIX C2 review code-reviewer 11/06 : PrevLevels (Phase 3) ecrit
            # `enriched["open_cash"] = close` AVANT le chain. Sub-engine 4 batch
            # semantique = `open` de bar us_start (different). Sans pop, sub-engine
            # 4 = code mort (set_diff exclut clef existante). Pop pour permettre
            # sub-engine 4 d'ecrire la valeur batch-fidele.
            enriched.pop("open_cash", None)
            # Convert bar_ts_utc datetime -> pandas.Timestamp (sub-engine 1 attendu)
            row_for_pbh = dict(enriched)
            row_for_pbh["ts_event"] = _pd.Timestamp(bar_ts_utc)
            # Chain ordre IMPOSE
            row_for_pbh = add_session_metadata_streaming(row_for_pbh, self._sm_state)
            row_for_pbh = add_ib_features_streaming(
                row_for_pbh, self._ib_state, tick=self.tick_size)
            row_for_pbh = add_session_high_low_streaming(
                row_for_pbh, self._shl_state, tick=self.tick_size)
            row_for_pbh = add_open_cash_price1030_streaming(
                row_for_pbh, self._ocp_state)
            # FIX C1 review code-reviewer 11/06 : DROP rename ib_atr_python.
            # `game_changers_streaming.py:204` consume `ib_atr` direct (PAS Sierra
            # natif qui s'appelle juste `atr`). Rename cassait day_type ->
            # NORM_VAR (2) permanent = port inert. Garde le nom `ib_atr` ;
            # collision Sierra `atr` est innexistante (verifie : Sierra emet `atr`
            # pour ATR 14 daily, jamais `ib_atr` natif).
            row_for_pbh = add_ib_atr_streaming(row_for_pbh, self._ib_atr_state)
            # Merge DIFF de cles (preserve Sierra natif si existant)
            # NB exclu "ts_event" (conversion locale)
            _produced = set(row_for_pbh) - set(enriched) - {"ts_event"}
            self._safe_update(enriched, {k: row_for_pbh[k] for k in _produced})
            if self._log_event is not None:
                try:
                    self._log_event("SIERRA_PORT_PHASE_B_HELPERS_OK",
                                     sym=self.symbol)
                except Exception:  # noqa: BLE001
                    pass
        except Exception as _e:  # noqa: BLE001
            if self._log_event is not None:
                try:
                    self._log_event("SIERRA_PORT_PHASE_B_HELPERS_FAIL",
                                     sym=self.symbol, err=str(_e)[:200])
                except Exception:  # noqa: BLE001
                    pass

        # ─── Phase 1 D2 - game_changers (5 features ressuscitees) ───────────
        # Sierra DMP emet placeholders (open_type=0, day_type=2, ...).
        # Python recalcule depuis inputs phase_b_helpers + Sierra aliases.
        # _safe_update + whitelist SIERRA_ZERO_NEVER_CALCULATED force override.
        try:
            _gc_out = add_game_changers_streaming(
                {**enriched}, self._gc_state, symbol=self.symbol)
            # FIX I1 review : DROP boucle force-override doublon. La whitelist
            # SIERRA_ZERO_NEVER_CALCULATED ligne ~225 contient deja open_direction
            # + trend_day_probability + (post-D2) open_type/zone, day_type,
            # open_bias_conf. `_safe_update` force override quand existing==0.0.
            # Strategy unique = whitelist (regle souveraine LOGS TRACABILITE
            # 01/05 : 1 source unique d'override, anti incoherence).
            _gc_produced = set(_gc_out) - set(enriched)
            self._safe_update(enriched, {k: _gc_out[k] for k in _gc_produced})
            # Force override des 4 placeholders Sierra (existant=0.0 OU 2 placeholder)
            for _gck in ("open_type", "open_zone", "day_type", "open_bias_conf"):
                _gcv = _gc_out.get(_gck)
                if _gcv is not None and _gcv == _gcv:  # not NaN
                    enriched[_gck] = _gcv
            if self._log_event is not None:
                try:
                    self._log_event("SIERRA_PORT_GAME_CHANGERS_OK",
                                     sym=self.symbol)
                except Exception:  # noqa: BLE001
                    pass
        except Exception as _e:  # noqa: BLE001
            if self._log_event is not None:
                try:
                    self._log_event("SIERRA_PORT_GAME_CHANGERS_FAIL",
                                     sym=self.symbol, err=str(_e)[:200])
                except Exception:  # noqa: BLE001
                    pass

        # ─── Phase 1 Group D - intermarket (10 features cross-sym ES/NQ) ────
        # Sierra DMP n'emet AUCUNE feature im_* native (0/10).
        # Caller (live_pipeline) doit appeler set_partner_bar(bar) AVANT
        # enrich_bar pour fournir le bar partner ES<->NQ.
        # Sans partner_bar : other_inputs=None -> 10 features = NaN propre.
        # Staleness check (mirror enricher_chain.py:696-722) :
        # - reject si partner_ts > target_ts (no future)
        # - reject si target_ts - partner_ts > 120s (stale)
        if self.symbol in ("ES", "NQ"):
            try:
                other_inputs = None
                partner_bar = self._partner_bar
                if partner_bar is not None:
                    partner_ts_ns = partner_bar.get("ts_event_ns", 0)
                    target_ts_ns = sierra_bar.get("ts_event_ns") or int(
                        bar_ts_utc.timestamp() * 1_000_000_000)
                    STALE_NS = 120 * 1_000_000_000
                    if partner_ts_ns > target_ts_ns:
                        partner_bar = None  # no future
                        if self._log_event is not None:
                            try:
                                self._log_event("SIERRA_PARTNER_STALE",
                                                 sym=self.symbol, reason="future")
                            except Exception:  # noqa: BLE001
                                pass
                    elif (target_ts_ns - partner_ts_ns) > STALE_NS:
                        partner_bar = None  # stale > 120s
                        if self._log_event is not None:
                            try:
                                self._log_event("SIERRA_PARTNER_STALE",
                                                 sym=self.symbol, reason="stale")
                            except Exception:  # noqa: BLE001
                                pass

                if partner_bar is not None:
                    # FIX MH1 review code-reviewer 11/06 : bug silent fallback `or`.
                    # `partner_bar.get("close") or partner_bar.get("price")` tombait
                    # sur price si close=0 (falsy mais valide). Remplace par check
                    # is not None explicit (mirror semantique enricher_chain.py:729-731).
                    _close = partner_bar.get("close")
                    _vol = partner_bar.get("total_vol")
                    other_inputs = {
                        "price": _close if _close is not None else partner_bar.get("price"),
                        "delta_bar": partner_bar.get("delta_bar"),
                        "total_vol": _vol if _vol is not None else partner_bar.get("volume"),
                        "delta_day": partner_bar.get("delta_day"),
                        "dist_sess_high": partner_bar.get("dist_sess_high"),
                        "dist_sess_low": partner_bar.get("dist_sess_low"),
                        "large_trader_ratio": partner_bar.get("large_trader_ratio"),
                        "open_bias_conf": partner_bar.get("open_bias_conf"),
                        "open_direction": partner_bar.get("open_direction"),
                        "open_type": partner_bar.get("open_type"),
                    }

                row_for_im = dict(enriched)
                if "price" not in row_for_im and "close" in row_for_im:
                    row_for_im["price"] = row_for_im["close"]
                im_out = add_intermarket_streaming(
                    row_for_im, self._intermarket_state,
                    other_inputs=other_inputs)
                # Merge uniquement im_* (evite price bloat)
                im_features = {k: v for k, v in im_out.items()
                                if k.startswith("im_")}
                self._safe_update(enriched, im_features)
                if self._log_event is not None:
                    try:
                        self._log_event("SIERRA_PORT_INTERMARKET_OK",
                                         sym=self.symbol)
                    except Exception:  # noqa: BLE001
                        pass
            except Exception as _e:  # noqa: BLE001
                if self._log_event is not None:
                    try:
                        self._log_event("SIERRA_PORT_INTERMARKET_FAIL",
                                         sym=self.symbol, err=str(_e)[:200])
                    except Exception:  # noqa: BLE001
                        pass

        # ─── Phase 1 Group D - D2/D3 NON PORTES (deps manquantes) ──────────
        # D2 game_changers (5 features open_type/zone, day_type, open_direction,
        #    open_bias_conf) : Sierra emet 5/5 PLACEHOLDERS (val=0/2/0/0.0).
        #    Inputs Python deps phase_b_helpers (prev_vah/val/vpoc, ib_high/low,
        #    ib_atr, sess_high/low, price_1030, date_et) ABSENTS du pipeline
        #    Sierra. Porter game_changers sans phase_b_helpers = critical_inputs_valid
        #    permanent False -> UNKNOWN broadcasting (PIRE que placeholder Sierra).
        #    Solution : porter phase_b_helpers d'abord (effort ~5h separe).
        # D3 absorb_streaming (10 features bn_absorb_*_zones_active,
        #    near_resistance/support_level, dist_last_spike_origin_pct) :
        #    requiert footprint_cells (absent Sierra). Meme blocker que C3 trapped.

        # ─── Fix A4 (11/06/2026) : Reconstruction dist_mq_*_pct manquants ───
        # Bug DMP C++ partiel : sur NQ `dist_mq_put_0dte_pct` est 100% NULL et
        # `dist_mq_call_0dte_pct` 50% NULL alors que les raw (ticks) sont OK.
        # Politique non-overwrite : recalcule UNIQUEMENT si pct est NULL.
        # Formule : pct = (dist_ticks * tick_size / close) * 100
        if close is not None and close > 0:
            _mq_raw_keys = (
                "dist_mq_put", "dist_mq_call", "dist_mq_hvl",
                "dist_mq_put_0dte", "dist_mq_call_0dte", "dist_mq_hvl_0dte",
            )
            for raw_key in _mq_raw_keys:
                pct_key = f"{raw_key}_pct"
                if enriched.get(pct_key) is None:
                    raw_val = enriched.get(raw_key)
                    if raw_val is not None:
                        try:
                            enriched[pct_key] = round(
                                (float(raw_val) * self.tick_size / close) * 100.0,
                                6,
                            )
                        except (TypeError, ValueError, ZeroDivisionError):
                            pass  # garde NULL si calcul echoue

        # ─── Fix anomalies 6+7 (11/06/2026 matin) : OVN + PDH/PDL distances ───
        # OVN : on a ovn_high/ovn_low (Sierra DMP raw) mais dist_ovn_high/low=null
        # et ovn_range_ticks=0 (bug C++). Phase 3 sessions_fine ECRASE
        # ovn_high/low par bar_high/low (premiere bar cold-start) -> on lit
        # depuis sierra_bar original pour avoir les vrais niveaux Sierra DMP.
        # PDH/PDL : pareil, on a dist_pdh_pct/pdl_pct OK mais dist_pdh_atr=null.
        # Convention Sierra confirmee : dist = level - close (cf bar live 09:36 UTC).
        # Politique non-overwrite : recalcule UNIQUEMENT si dist est NULL.
        if close is not None and close > 0 and self.tick_size > 0:
            # Anomalie 6 : OVN. Sierra DMP n'expose PAS ovn_high/low dans le RAW
            # JSONL - ils sont calcules par Phase 3 (sessions_fine). On lit donc
            # depuis enriched (Phase 3 output) pour avoir les vrais niveaux.
            ovn_high_raw = enriched.get("ovn_high")
            ovn_low_raw = enriched.get("ovn_low")
            if enriched.get("dist_ovn_high") is None and ovn_high_raw is not None:
                try:
                    enriched["dist_ovn_high"] = round(
                        (float(ovn_high_raw) - close) / self.tick_size, 4)
                except (TypeError, ValueError):
                    pass
            if enriched.get("dist_ovn_low") is None and ovn_low_raw is not None:
                try:
                    enriched["dist_ovn_low"] = round(
                        (float(ovn_low_raw) - close) / self.tick_size, 4)
                except (TypeError, ValueError):
                    pass
            # ovn_range_ticks : DMP C++ retourne 0 par bug.
            cur_range = enriched.get("ovn_range_ticks")
            if (cur_range in (None, 0, 0.0)
                and ovn_high_raw is not None and ovn_low_raw is not None):
                try:
                    enriched["ovn_range_ticks"] = round(
                        (float(ovn_high_raw) - float(ovn_low_raw)) / self.tick_size, 4)
                except (TypeError, ValueError):
                    pass

            # Anomalie 7 : PDH/PDL ATR-normalises (lecture sierra_bar)
            # prev_levels.PrevLevelsCalculator retourne np.nan en cold-start,
            # ecrit dans enriched. On considere None ET NaN comme "vide".
            import math as _m
            def _is_empty(v):
                if v is None: return True
                if isinstance(v, float) and _m.isnan(v): return True
                return False

            atr_raw = sierra_bar.get("atr")  # Sierra ATR en TICKS
            if atr_raw is not None and atr_raw > 0:
                pdh_raw = sierra_bar.get("pdh")
                pdl_raw = sierra_bar.get("pdl")
                if _is_empty(enriched.get("dist_pdh_atr")) and pdh_raw is not None:
                    try:
                        dist_ticks = (float(pdh_raw) - close) / self.tick_size
                        enriched["dist_pdh_atr"] = round(dist_ticks / atr_raw, 6)
                    except (TypeError, ValueError, ZeroDivisionError):
                        pass
                if _is_empty(enriched.get("dist_pdl_atr")) and pdl_raw is not None:
                    try:
                        dist_ticks = (float(pdl_raw) - close) / self.tick_size
                        enriched["dist_pdl_atr"] = round(dist_ticks / atr_raw, 6)
                    except (TypeError, ValueError, ZeroDivisionError):
                        pass

        # Meta orchestrateur
        enriched["_phase3_enriched"] = True
        enriched["_phase3_bars_processed"] = self._bars_processed

        # Phase 1.5 (12/06/2026) - Normalisation timestamp Sierra LIVE.
        # Sierra Chart emet bars 1-min avec jitter +/-1s (31% bars a :59
        # empirique 12/06 NQ live). Fix : ROUND ts a la minute nominale +
        # preserve ts_raw_ms brut + reconstitue ts_event ISO + ts_event_ns
        # coherents. Cf CORE/sierra_ts.py + INCIDENT_LOG #48.
        # Contrat post-normalisation = propriete de l'orchestrator (1 fix
        # couvre les 3 entry points : batch + live mono + live multi).
        #
        # ORDRE Phase A.4 (12/06 PM, review code-reviewer reserve #3) :
        # normalize_payload_ts AVANT Market Profile sub-engines, sinon
        # CompositePOCState._ts_to_trading_day lit le ts brut Sierra avec
        # jitter +/-1s -> frontiere CME 22:00 UTC potentiellement franchie
        # 1s trop tot/tard -> archive VPOC dans le mauvais trading day.
        enriched = normalize_payload_ts(enriched)

        # Phase A.2a + A.3 (12/06/2026 PM) - Market Profile + ICT/Wyckoff
        # Enrichissement Python avec ~28 nouvelles features Dalton/Steidlmayer/ICT :
        #   EASY (12 features) : PSD+2/-2, Open Relation Type, Profile Overlap,
        #                        Range Extension vs IB, FVG (Fair Value Gap)
        #   MEDIUM (16 features) : Single Prints + position, Composite POC 5d/20d,
        #                          Liquidity Sweep detector, Judas Swing detector
        # Aucune dependance externe : utilise features pipeline existantes.
        # Cf CORE/market_profile_v5.py + CORE/market_profile_advanced.py.
        # Cf INCIDENT_LOG #51 (audit narration NQ live cross-check 2 agents).
        try:
            mp_v5_feats = compute_market_profile_v5_features(
                enriched, self._fvg_state
            )
            enriched.update(mp_v5_feats)
        except Exception as _e:  # noqa: BLE001
            if self._log_event is not None:
                try:
                    self._log_event("SIERRA_PORT_MARKET_PROFILE_V5_FAIL",
                                     sym=self.symbol, err=str(_e)[:200])
                except Exception:  # noqa: BLE001
                    pass

        try:
            mp_adv_feats = compute_market_profile_advanced_features(
                enriched, self._market_profile_advanced_state
            )
            enriched.update(mp_adv_feats)
        except Exception as _e:  # noqa: BLE001
            if self._log_event is not None:
                try:
                    self._log_event("SIERRA_PORT_MARKET_PROFILE_ADV_FAIL",
                                     sym=self.symbol, err=str(_e)[:200])
                except Exception:  # noqa: BLE001
                    pass

        return enriched

    def set_partner_bar(self, partner_bar: Optional[dict]) -> None:
        """Phase 1 Group D - injecte le bar du symbole partenaire pour intermarket.

        Convention cross-symbole (mirror enricher_chain.py:687-722) :
        - ES.enrich_bar(es_bar) cycle : caller appelle pipe_es.set_partner_bar(last_nq_bar)
        - NQ.enrich_bar(nq_bar) cycle : caller appelle pipe_nq.set_partner_bar(last_es_bar)
        - Staleness + no-future verifies dans enrich_bar (reject si > 120s ou future)

        TODO MH2 review code-reviewer 11/06 :
        En PROD actuelle, BOT/run_sierra_enricher.py lance 1 process par symbole
        sans memoire partagee. AUCUN caller n'appelle set_partner_bar -> 10 features
        im_* seront 100% NaN en paper J+1.
        Plan post-Phase 1 : multi-symbol orchestrator (mode --multi-symbol) qui
        instancie ES+NQ dans le meme process + cross-injection partner_bar.
        Pas bloquant pour Phase 1 (NaN propre, modeles ML defensifs) mais a corriger
        avant Phase 4 dual-run parity Sierra vs Databento (Sierra im_*=NaN vs
        Databento im_*=valeurs -> divergence faussera la metrique parite).
        Anti pattern_11 : NE PAS gate les bots sur im_*=NaN tant que ce port
        n'est pas activement aliemente.

        Args:
            partner_bar : dict bar partenaire enrichi (avec close, delta_bar,
                           total_vol, delta_day, dist_sess_high/low,
                           large_trader_ratio, open_*, ts_event_ns).
                           None = reset partner (features im_* = NaN cycle suivant).
        """
        # NB thread-safety : dict assignment atomique CPython (GIL), mais
        # documenter "1 instance = 1 symbole, pas thread-safe" reste valide.
        self._partner_bar = partner_bar

    def _maybe_cross_day_reset(self, trading_date: date) -> bool:
        """Reset cross-day si trading_date change. Returns True si reset effectue."""
        if self._current_trading_date is None:
            self._current_trading_date = trading_date
            self._cvd_session_running = 0.0  # reset cvd_session cumsum
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
        # Phase 1 Group A : reset cvd_session cumsum cross-day
        self._cvd_session_running = 0.0
        # Reset long/color bar states (factories deja importees top-of-file
        # avec fallback CORE/ - cf review CRITIQUE 3 : pas d'import local).
        self._long_bar_state = make_long_bar_state(self.symbol)
        self._color_bar_state = make_color_bar_state(self.symbol)
        # Phase 1 Group B : reset rolling_features + edge_zones + delta_div_ext
        # rolling_features_streaming gere lui-meme le reset cvd_session via
        # `current_trading_date` interne (cf sub-engine delta_div + session)
        # mais on reset le state au cas ou pour safety.
        self._rolling_state = RollingFeaturesState()
        self._edge_buy_buffer = ExtensionLineBuffer()
        self._edge_sell_buffer = ExtensionLineBuffer()
        self._edge_bar_idx = 0
        # Phase 1 Group C - rvol state reset (cold-start 4 bars rvol=1.0
        # chaque session, conforme batch mode RvolEngine.compute qui traite
        # chaque DataFrame independamment - review NICE-TO-HAVE #3)
        self._rvol_state = RvolEngineState()
        # Phase 1 Group D - intermarket reset
        self._intermarket_state = IntermarketState()
        # partner_bar NE PAS reset (le caller cross-symbole gere son cycle)
        # Phase 1 D2 - phase_b_helpers + game_changers reset
        # Note : session_metadata + open_cash + game_changers gerent leur propre
        # date_et internal mais on reset au cas ou pour safety (idempotent).
        self._sm_state = SessionMetadataState()
        self._ib_state = IBState()
        self._shl_state = SessionHighLowState()
        self._ocp_state = OpenCashPrice1030State()
        # ib_atr garde 14j lookback : NE PAS reset (sinon ib_atr=NaN chaque
        # session pendant 3 jours min_periods)
        self._gc_state = GameChangersState()
        # Phase A.4 (12/06 PM) : reset Market Profile + ICT/Wyckoff states
        # cross-day pour eviter faux signaux J+1 (FVG accumules, sweeps obsoletes,
        # London open zombie). Composite POC gere son propre cross-day via
        # _ts_to_trading_day mais on reset au cas ou pour safety.
        # Cf review code-reviewer Phase A.4 reserve #2.
        self._fvg_state = FVGState()
        self._market_profile_advanced_state = MarketProfileAdvancedState()
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
